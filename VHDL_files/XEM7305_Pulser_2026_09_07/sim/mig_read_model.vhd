-------------------------------------------------------------------------------
-- mig_read_model  (SIMULATION MODEL)
--
-- Minimal behavioural model of the MIG 7-series native app interface, read
-- side only, for exercising ddr3_line_streamer. It:
--   * accepts a read command when app_en & app_rdy & app_cmd="001",
--   * after READ_LATENCY ui_clk cycles pulses app_rd_data_valid with data,
--   * returns data computed from the address so ordering is self-checking:
--       one 128-bit beat at app_addr = beat*ADDR_INC carries
--         low  64 bits = line index (2*beat),
--         high 64 bits = line index (2*beat + 1),
--     so a correctly-ordered low-first stream pops lines 0,1,2,3,...
--
-- Options (default off): DROP_EVERY injects the Phase 6b "lost command"
-- (app_rdy accepted, no valid returned) every Nth accept to exercise the
-- streamer's retry; STALL_MASK deasserts app_rdy on some cycles for backpressure.
--
-- This models the DIGITAL handshake only. It deliberately does NOT model the
-- cold-start row mis-address (a silicon-timing effect) -- so a clean sim proves
-- the streamer logic, not the heartbeat's physical effectiveness.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity mig_read_model is
  generic (
    ADDR_WIDTH   : natural := 29;
    ADDR_INC     : natural := 8;
    READ_LATENCY : natural := 24;
    DROP_EVERY   : natural := 0;   -- 0 = never drop; else drop every Nth accepted read
    STALL_MASK   : natural := 0    -- 0 = always ready; else app_rdy low when (cycle mod (STALL_MASK+1))=0
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

architecture behav of mig_read_model is
  signal rdy_i       : std_logic := '1';
  signal pend_active : std_logic := '0';
  signal pend_addr   : unsigned(ADDR_WIDTH-1 downto 0) := (others => '0');
  signal pend_cnt    : integer range 0 to 65535 := 0;
  signal pend_drop   : std_logic := '0';        -- this pending read is a dropped one
  signal accept_num  : integer := 0;            -- count of accepted reads (for DROP_EVERY)
  signal cyc         : integer := 0;            -- free-running cycle (for STALL_MASK)
begin

  app_rdy <= rdy_i;

  process (ui_clk)
    variable beat : integer;
  begin
    if rising_edge(ui_clk) then
      app_rd_data_valid <= '0';
      cyc <= cyc + 1;

      -- backpressure model
      if STALL_MASK /= 0 and (cyc mod (STALL_MASK+1)) = 0 then
        rdy_i <= '0';
      else
        rdy_i <= '1';
      end if;

      if ui_rst = '1' then
        pend_active <= '0';
        pend_drop   <= '0';
        accept_num  <= 0;
      else
        -- accept a new read (single outstanding is all the streamer issues)
        if app_en = '1' and rdy_i = '1' and app_cmd = "001" and pend_active = '0' then
          pend_addr   <= unsigned(app_addr);
          pend_cnt    <= READ_LATENCY;
          pend_active <= '1';
          accept_num  <= accept_num + 1;
          if DROP_EVERY /= 0 and ((accept_num + 1) mod DROP_EVERY) = 0 then
            pend_drop <= '1';   -- swallow this one: never return a valid
          else
            pend_drop <= '0';
          end if;
        end if;

        -- service the pending read
        if pend_active = '1' then
          if pend_cnt <= 1 then
            if pend_drop = '0' then
              beat := to_integer(pend_addr) / ADDR_INC;
              app_rd_data <= std_logic_vector(to_unsigned(2*beat + 1, 64)) &
                             std_logic_vector(to_unsigned(2*beat, 64));
              app_rd_data_valid <= '1';
              pend_active <= '0';
            else
              -- dropped: clear the pending slot without ever asserting valid,
              -- so the streamer's retry timeout must recover it.
              pend_active <= '0';
              pend_drop   <= '0';
            end if;
          else
            pend_cnt <= pend_cnt - 1;
          end if;
        end if;
      end if;
    end if;
  end process;

end architecture;
