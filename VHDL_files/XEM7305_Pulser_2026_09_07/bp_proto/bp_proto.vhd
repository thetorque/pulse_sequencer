-- bp_proto.vhd -- DDS bus PROTOCOL test sender, master side (XEM7305 carrier).
-- Standalone (no FrontPanel), 200 MHz sys_clk. Speaks DDS_BUS_CONTRACT.md v0.2 to every
-- DDS board (broadcast address 0x1F), to test the slave's dds_top end to end before the
-- real Phase-4 0x81 serializer exists.
--
-- Loop (~25 s), repeated forever (so a DDS board that boots late still gets the table):
--   1. WRITE_ROWS  START=0, 5 rows (FTW @ 1 GHz SYSCLK, POW 0, VGA 0xB40 ~0 dBm @ 50 MHz):
--        row 0  50 MHz  RF on      row 3  200 MHz  RF on
--        row 1 100 MHz  RF on      row 4  200 MHz  RF OFF (tests CTRL.RF_ON)
--        row 2 150 MHz  RF on
--   2. RESET frame      -> row 0 live          (RAMRESET line not wired on the coupler)
--   3. every ~5 s: a 120 ns STEPNEXT pulse      -> rows 1, 2, 3, 4
--   4. ~5 s after the last step, back to 1.
-- Bus: SCK = 25 MHz (200 MHz / 8), SPI mode 0, MSB first, CS-high gap 1 us.
-- RAMRESET / AUX1-3 held low.
-- Master LEDs: D4..D8 = expected live row (0..4), D10 = frame being sent, D11 heartbeat.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library unisim;
use unisim.vcomponents.all;

entity bp_proto is
  port (
    sys_clk_p, sys_clk_n : in  std_logic;
    led_out : out std_logic_vector(7 downto 0);
    bp      : out std_logic_vector(7 downto 0)   -- 0 SCK 1 MOSI 2 CS 3 STEPNEXT 4 RAMRESET 5-7 AUX
  );
end entity;

architecture rtl of bp_proto is
  -- frame ROM: 9 bits = {end-of-frame flag, byte}
  type rom_t is array (0 to 60) of std_logic_vector(8 downto 0);
  constant ROM : rom_t := (
    "000011111",  -- 0x1F
    "000000001",  -- 0x01
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "000001100",  -- 0x0C
    "011001100",  -- 0xCC
    "011001100",  -- 0xCC
    "011001100",  -- 0xCC
    "011001100",  -- 0xCC
    "011001101",  -- 0xCD
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "010110100",  -- 0xB4
    "000000000",  -- 0x00
    "000000001",  -- 0x01
    "000011001",  -- 0x19
    "010011001",  -- 0x99
    "010011001",  -- 0x99
    "010011001",  -- 0x99
    "010011001",  -- 0x99
    "010011010",  -- 0x9A
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "010110100",  -- 0xB4
    "000000000",  -- 0x00
    "000000001",  -- 0x01
    "000100110",  -- 0x26
    "001100110",  -- 0x66
    "001100110",  -- 0x66
    "001100110",  -- 0x66
    "001100110",  -- 0x66
    "001100110",  -- 0x66
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "010110100",  -- 0xB4
    "000000000",  -- 0x00
    "000000001",  -- 0x01
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "010110100",  -- 0xB4
    "000000000",  -- 0x00
    "000000001",  -- 0x01
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000110011",  -- 0x33
    "000000000",  -- 0x00
    "000000000",  -- 0x00
    "010110100",  -- 0xB4
    "000000000",  -- 0x00
    "100000000",  -- EOF 0x00
    "000011111",  -- 0x1F
    "100000010"  -- EOF 0x02
  );
  constant F_ROWS  : integer := 0;      -- WRITE_ROWS frame start
  constant F_RESET : integer := 59;      -- RESET frame start

  constant HALF    : integer := 4;               -- SCK half period, 200 MHz clks -> 25 MHz
  constant GAP     : integer := 200;             -- CS-high gap after a frame (1 us)
  constant DWELL   : integer := 1_000_000_000;   -- ~5 s
  constant PULSE   : integer := 24;              -- STEPNEXT width (120 ns)

  signal clk_i, clk : std_logic;

  -- serializer
  type ser_t is (S_IDLE, S_LOAD, S_LO, S_HI, S_GAP);
  signal ss    : ser_t := S_IDLE;
  signal idx   : integer range 0 to ROM'length-1 := 0;
  signal sh    : std_logic_vector(7 downto 0) := (others => '0');
  signal eof   : std_logic := '0';
  signal nbit  : integer range 0 to 7 := 0;
  signal hc    : integer range 0 to GAP := 0;
  signal s_go  : std_logic := '0';
  signal s_at  : integer range 0 to ROM'length-1 := 0;
  signal s_busy: std_logic := '0';
  signal sck_r, mosi_r : std_logic := '0';
  signal cs_r : std_logic := '1';

  -- sequencer
  type seq_t is (Q_START, Q_ROWS, Q_RESET, Q_DWELL, Q_STEP);
  signal qs    : seq_t := Q_START;
  signal row   : integer range 0 to 4 := 0;
  signal tcnt  : integer range 0 to DWELL := 0;
  signal step_r: std_logic := '0';
  signal hb    : unsigned(27 downto 0) := (others => '0');
begin
  ibuf : IBUFGDS generic map ( DIFF_TERM => FALSE, IOSTANDARD => "LVDS_25" )
                 port map ( I => sys_clk_p, IB => sys_clk_n, O => clk_i );
  bufg_i : BUFG port map ( I => clk_i, O => clk );

  -- ---------------- frame serializer ----------------
  process(clk) begin
    if rising_edge(clk) then
      case ss is
        when S_IDLE =>
          cs_r <= '1'; sck_r <= '0';
          if s_go = '1' then idx <= s_at; s_busy <= '1'; cs_r <= '0'; hc <= 0; ss <= S_LOAD;
          else s_busy <= '0'; end if;
        when S_LOAD =>                              -- (CS already low)
          sh <= ROM(idx)(7 downto 0); eof <= ROM(idx)(8); nbit <= 0; hc <= 0; ss <= S_LO;
        when S_LO =>                                -- SCK low, MOSI = bit
          sck_r <= '0'; mosi_r <= sh(7);
          if hc = HALF-1 then hc <= 0; ss <= S_HI; else hc <= hc + 1; end if;
        when S_HI =>                                -- SCK high: slave samples
          sck_r <= '1';
          if hc = HALF-1 then
            hc <= 0; sh <= sh(6 downto 0) & '0';
            if nbit = 7 then
              if eof = '1' then ss <= S_GAP;
              else idx <= idx + 1; ss <= S_LOAD; end if;
            else
              nbit <= nbit + 1; ss <= S_LO;
            end if;
          else
            hc <= hc + 1;
          end if;
        when S_GAP =>                               -- half bit low, then CS high for GAP
          sck_r <= '0';
          if hc = HALF-1 then cs_r <= '1'; end if;
          if hc = GAP then ss <= S_IDLE; s_busy <= '0'; else hc <= hc + 1; end if;
      end case;
    end if;
  end process;

  -- ---------------- test sequencer ----------------
  process(clk) begin
    if rising_edge(clk) then
      hb <= hb + 1;
      s_go <= '0';
      case qs is
        when Q_START =>                             -- send the table
          if s_busy = '0' and s_go = '0' then s_at <= F_ROWS; s_go <= '1'; qs <= Q_ROWS; end if;
        when Q_ROWS =>
          if s_busy = '0' and s_go = '0' and ss = S_IDLE then
            s_at <= F_RESET; s_go <= '1'; qs <= Q_RESET;
          end if;
        when Q_RESET =>                             -- RESET frame -> row 0
          if s_busy = '0' and s_go = '0' and ss = S_IDLE then
            row <= 0; tcnt <= 0; qs <= Q_DWELL;
          end if;
        when Q_DWELL =>
          if tcnt = DWELL then
            tcnt <= 0;
            if row = 4 then qs <= Q_START;
            else step_r <= '1'; qs <= Q_STEP; end if;
          else
            tcnt <= tcnt + 1;
          end if;
        when Q_STEP =>                              -- 120 ns STEPNEXT pulse
          if tcnt = PULSE then
            step_r <= '0'; tcnt <= 0; row <= row + 1; qs <= Q_DWELL;
          else
            tcnt <= tcnt + 1;
          end if;
      end case;
    end if;
  end process;

  bp <= "0000" & step_r & cs_r & mosi_r & sck_r;

  gen_led : for i in 0 to 4 generate
    led_out(i) <= '1' when row = i else '0';
  end generate;
  led_out(5) <= '0';
  led_out(6) <= not cs_r;
  led_out(7) <= hb(27);
end architecture;
