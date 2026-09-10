-------------------------------------------------------------------------------
-- mig_ramp_model  (SIMULATION MODEL)
--
-- Like mig_prog_model, but serves a LONG computed ramp program instead of a
-- fixed 32-line array, so a testbench can drive the terminator far past the
-- streamer's prime window / FIFO depth -- the sustained-streaming case the
-- hardware --long test exposed and the fixed models never reached.
--
--   line(i) = time=(i+1)*DWELL (61:32), channel=(i mod 4095)+1 (31:0)  for i<NPROG
--   line(i) = 0 (terminator / padding)                                 for i>=NPROG
--
-- One 128-bit beat at app_addr=beat*ADDR_INC carries low=line(2*beat),
-- high=line(2*beat+1); the streamer swaps halves so the 64/128 FIFO emits the
-- low (first) line first. Single outstanding, READ_LATENCY cycles.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity mig_ramp_model is
  generic (
    ADDR_WIDTH   : natural := 29;
    ADDR_INC     : natural := 8;
    READ_LATENCY : natural := 24;
    DWELL        : natural := 10;      -- ticks between lines
    NPROG        : natural := 1200     -- real lines before the terminator
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

architecture behav of mig_ramp_model is
  -- one program line as the sequencer decodes it (time 61:32, channel 31:0)
  function mkline(i : integer) return std_logic_vector is
    variable t  : integer;
    variable ch : integer;
  begin
    if i < 0 or i >= NPROG then
      return (63 downto 0 => '0');       -- terminator / padding
    end if;
    t  := (i + 1) * DWELL;
    ch := (i mod 4095) + 1;
    -- line = "00"(63:62) & time(61:32) & channel(31:0) = 64 bits
    return "00" & std_logic_vector(to_unsigned(t, 30)) & std_logic_vector(to_unsigned(ch, 32));
  end function;

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
            lo := mkline(2*beat);
            hi := mkline(2*beat+1);
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
