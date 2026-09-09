-------------------------------------------------------------------------------
-- mig_prog_model  (SIMULATION MODEL)
--
-- Like mig_read_model but its backing memory holds a real pulse-sequence
-- PROGRAM, so the streamer + pulse_sequencer can be simulated end to end.
--
-- Line format (matches photon.vhd's sequencer FSM):
--   bits [31:0]  = channel / TTL state (drives master_logic)
--   bits [61:32] = time (30-bit); the sequencer holds a line's channel for the
--                  NEXT line's time (in 40 ns ticks). time = 0 is the terminator.
-- One 128-bit beat at app_addr = beat*ADDR_INC carries low = line(2*beat),
-- high = line(2*beat+1); the 128/64 FIFO reads low-first, so the sequencer
-- pops lines 0,1,2,... in order.
--
-- `time` is the ABSOLUTE tick count at which the state changes (cumulative,
-- increasing) -- matching photon.vhd, where the FSM's time_count free-runs and
-- is compared against each line's time. Program below (channel, abs-time):
--   L0 (0x1, -)  L1 (0x2, 3)  L2 (0x4, 8)  L3 (0x8, 10)  L4 = terminator (0)
-- L0.time is unused (a line's channel is held until the NEXT line's time).
-- Expected output: 0x1 for 3 ticks, 0x2 for 5 (3->8), 0x4 for 2 (8->10), then
-- 0 (L3=0x8, the line before the terminator, is never emitted).
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity mig_prog_model is
  generic (
    ADDR_WIDTH   : natural := 29;
    ADDR_INC     : natural := 8;
    READ_LATENCY : natural := 24;
    PROG_SEL     : natural := 0    -- 0 = 3-pulse demo; 1 = 11-pulse short-dwell stress
  );
  port (
    ui_clk            : in  std_logic;
    ui_rst            : in  std_logic;
    app_addr          : in  std_logic_vector(ADDR_WIDTH-1 downto 0);
    app_cmd           : in  std_logic_vector(2 downto 0);
    app_en            : in  std_logic;
    app_rdy           : out std_logic;
    app_rd_data       : out std_logic_vector(127 downto 0);
    app_rd_data_valid : out std_logic
  );
end entity;

architecture behav of mig_prog_model is

  -- one 64-bit line = time(61:32) & channel(31:0)
  function mk(ch : integer; t : integer) return std_logic_vector is
  begin
    return std_logic_vector(to_unsigned(t, 32)) & std_logic_vector(to_unsigned(ch, 32));
  end function;

  constant NLINES : integer := 32;
  type prog_t is array(0 to NLINES-1) of std_logic_vector(63 downto 0);
  constant PROG0 : prog_t := (
    0 => mk(16#1#, 0),      -- L0.time unused
    1 => mk(16#2#, 3),      -- change to 0x2 at t=3
    2 => mk(16#4#, 8),      -- change to 0x4 at t=8
    3 => mk(16#8#, 10),     -- (line before terminator; channel not emitted)
    4 => mk(0, 0),          -- terminator (time field 0)
    others => (others => '0')
  );

  -- 11 pulses, channels 1..11, each held exactly one 40 ns tick (abs times
  -- 1,2,3,...). Consumes 1 line/40 ns -- faster than the streamer produces
  -- (~166 ns/line) -- so once the small prime buffer drains the sequencer must
  -- stall. Emitted channels must still be 1,2,...,11 in order (stretched, but
  -- never garbage or out of order).
  function stress return prog_t is
    variable p : prog_t := (others => (others => '0'));
  begin
    for k in 0 to 11 loop p(k) := mk(k+1, k); end loop;  -- L0.time=0 unused
    p(12) := mk(0, 0);                                    -- terminator
    return p;
  end function;

  function sel_prog return prog_t is
  begin
    if PROG_SEL = 0 then return PROG0; else return stress; end if;
  end function;

  constant PROG : prog_t := sel_prog;

  signal pend_active : std_logic := '0';
  signal pend_addr   : unsigned(ADDR_WIDTH-1 downto 0) := (others => '0');
  signal pend_cnt    : integer range 0 to 65535 := 0;
begin

  app_rdy <= not pend_active;   -- single outstanding: not ready while busy

  process (ui_clk)
    variable beat : integer;
    variable lo, hi : std_logic_vector(63 downto 0);
  begin
    if rising_edge(ui_clk) then
      app_rd_data_valid <= '0';
      if ui_rst = '1' then
        pend_active <= '0';
      else
        if app_en = '1' and pend_active = '0' and app_cmd = "001" then
          pend_addr   <= unsigned(app_addr);
          pend_cnt    <= READ_LATENCY;
          pend_active <= '1';
        end if;
        if pend_active = '1' then
          if pend_cnt <= 1 then
            beat := to_integer(pend_addr) / ADDR_INC;
            if 2*beat   < NLINES then lo := PROG(2*beat);   else lo := (others => '0'); end if;
            if 2*beat+1 < NLINES then hi := PROG(2*beat+1); else hi := (others => '0'); end if;
            app_rd_data       <= hi & lo;
            app_rd_data_valid <= '1';
            pend_active       <= '0';
          else
            pend_cnt <= pend_cnt - 1;
          end if;
        end if;
      end if;
    end if;
  end process;

end architecture;
