-- bp_fast.vhd -- backplane SPEED test, master side (XEM7305 carrier).
--
-- Standalone (no FrontPanel). Clock: the module's 200 MHz LVDS sys_clk (R2/R1), so the
-- SCK rates are exact. Exercises the 4 bus lines that the protocol uses:
--   SCK   free-running only inside a frame, SCK = 100/NH MHz
--   MOSI  continuous PRBS7 (x^7+x^6+1) bit stream, changes on SCK falling edge,
--         stable on the rising edge (SPI mode 0); continues across frames
--   CS    low for exactly 32 SCK cycles per frame, then high for 4 bit-times
--   STEPNEXT one high pulse (1 bit-time) in the gap of every frame
-- RAMRESET / AUX1-3 are held low.
-- The SCK rate steps every ~10 s (only at a frame boundary):
--   k : 0     1     2     3      4      5      6
--   SCK 1 MHz 2 MHz 5 MHz 10 MHz 20 MHz 25 MHz 33.3 MHz
-- Master LEDs: D4..D10 = rate index k (one lit), D11 = ~1 Hz heartbeat.
-- Pair with the DDS board's bp_fast_rx.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library unisim;
use unisim.vcomponents.all;

entity bp_fast is
  port (
    sys_clk_p, sys_clk_n : in  std_logic;
    led_out : out std_logic_vector(7 downto 0);
    bp      : out std_logic_vector(7 downto 0)   -- 0 SCK 1 MOSI 2 CS 3 STEPNEXT 4 RAMRESET 5-7 AUX1-3
  );
end entity;

architecture rtl of bp_fast is
  type nh_t is array (0 to 6) of integer range 1 to 100;
  constant NH_TAB : nh_t := (100, 50, 20, 10, 5, 4, 3);    -- SCK half-period, 5 ns units
  constant DWELL  : integer := 2_000_000_000 - 1;          -- ~10 s @ 200 MHz
  constant FBITS  : integer := 32;                          -- bits per frame (CS low)
  constant NBITS  : integer := 36;                          -- + 4 gap bit-times

  signal clk_i, clk : std_logic;
  signal k     : integer range 0 to 6 := 0;
  signal dwell_c : integer range 0 to DWELL := 0;
  signal nh    : integer range 1 to 100 := 100;
  signal pc    : integer range 0 to 199 := 0;               -- position within bit time
  signal bitn  : integer range 0 to NBITS - 1 := NBITS - 1; -- start in the gap
  signal prbs  : std_logic_vector(6 downto 0) := "1010110";
  signal mbit  : std_logic := '0';
  signal hb    : unsigned(27 downto 0) := (others => '0');
  signal sck_r, mosi_r, cs_r, step_r : std_logic := '0';
begin
  ibuf : IBUFGDS generic map ( DIFF_TERM => FALSE, IOSTANDARD => "LVDS_25" )
                 port map ( I => sys_clk_p, IB => sys_clk_n, O => clk_i );
  bufg_i : BUFG port map ( I => clk_i, O => clk );

  process(clk)
    variable nb : std_logic;
  begin
    if rising_edge(clk) then
      hb <= hb + 1;

      -- rate dwell timer
      if dwell_c = DWELL then
        dwell_c <= 0;
        if k = 6 then k <= 0; else k <= k + 1; end if;
      else
        dwell_c <= dwell_c + 1;
      end if;

      -- bit timing
      if pc = 2 * nh - 1 then
        pc <= 0;
        if bitn = NBITS - 1 then
          bitn <= 0;
          nh   <= NH_TAB(k);                       -- rate changes only between frames
        else
          bitn <= bitn + 1;
        end if;
        if bitn = NBITS - 1 or bitn + 1 < FBITS then   -- next bit is a frame bit
          nb   := prbs(6) xor prbs(5);
          prbs <= prbs(5 downto 0) & nb;
          mbit <= nb;
        end if;
      else
        pc <= pc + 1;
      end if;

      -- registered outputs
      if bitn < FBITS then
        cs_r <= '0';
        if pc >= nh then sck_r <= '1'; else sck_r <= '0'; end if;
      else
        cs_r <= '1'; sck_r <= '0';
      end if;
      mosi_r <= mbit;
      if bitn = FBITS + 1 then step_r <= '1'; else step_r <= '0'; end if;
    end if;
  end process;

  bp <= "0000" & step_r & cs_r & mosi_r & sck_r;

  gen_led : for i in 0 to 6 generate
    led_out(i) <= '1' when k = i else '0';
  end generate;
  led_out(7) <= hb(27);
end architecture;
