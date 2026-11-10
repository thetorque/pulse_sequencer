-- bp_test.vhd -- backplane link test, master side (XEM7305 carrier).
--
-- Standalone (no FrontPanel endpoints, no external clock; STARTUPE2 CFGMCLK ~65 MHz).
-- Drives the 8 backplane lines through the DS90LV047A LVDS drivers with the SAME
-- pattern as the master's own status LEDs D4..D11, so the two boards can be compared
-- side by side (pair with the DDS board's bp_rx):
--   idx  line                 master LED   DDS LED (bp_rx)
--    0   BACKPLANE_SCK        D4           D1 green
--    1   BACKPLANE_MOSI       D5           D2 green
--    2   BACKPLANE_CS         D6           D3 green
--    3   BACKPLANE_STEPNEXT   D7           D4 green
--    4   BACKPLANE_RAMRESET   D8           D5 green
--    5   BACKPLANE_AUX1       D9           D6 green
--    6   BACKPLANE_AUX2       D10          D1 red
--    7   BACKPLANE_AUX3       D11          D2 red
-- Pattern (repeats, ~7 s): one line high at a time, idx 0 -> 7 (~0.5 s each),
-- then all 8 high (~1 s), then all 8 low (~2 s).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library unisim;
use unisim.vcomponents.all;

entity bp_test is
  port (
    led_out : out std_logic_vector(7 downto 0);
    bp      : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of bp_test is
  signal clk  : std_logic;
  signal tick : unsigned(24 downto 0) := (others => '0');   -- ~0.5 s per step
  signal step : unsigned(3 downto 0)  := (others => '0');   -- 0..7 walk, 8-9 all high, 10-13 all low
  signal pat  : std_logic_vector(7 downto 0);
begin
  u_startup : STARTUPE2
    generic map ( PROG_USR => "FALSE", SIM_CCLK_FREQ => 0.0 )
    port map ( CFGCLK => open, CFGMCLK => clk, EOS => open, PREQ => open,
               CLK => '0', GSR => '0', GTS => '0', KEYCLEARB => '1', PACK => '0',
               USRCCLKO => '0', USRCCLKTS => '1', USRDONEO => '1', USRDONETS => '1' );

  process(clk) begin
    if rising_edge(clk) then
      tick <= tick + 1;
      if tick = (tick'range => '1') then
        if step = 13 then step <= (others => '0'); else step <= step + 1; end if;
      end if;
    end if;
  end process;

  process(step) begin
    if step < 8 then
      pat <= (others => '0');
      pat(to_integer(step(2 downto 0))) <= '1';
    elsif step < 10 then
      pat <= (others => '1');
    else
      pat <= (others => '0');
    end if;
  end process;

  led_out <= pat;
  bp      <= pat;
end architecture;
