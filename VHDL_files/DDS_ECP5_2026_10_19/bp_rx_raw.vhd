-- bp_rx_raw.vhd -- backplane link test, DDS side, RAW mirror (no clock, no gating).
--
-- Each LED = the received line level directly (line HIGH = LED lit; LEDs active-low):
--   backplane_sck      -> D1 green     backplane_ramreset -> D5 green
--   backplane_mosi     -> D2 green     backplane_aux1     -> D6 green
--   backplane_cs       -> D3 green     backplane_aux2     -> D1 red
--   backplane_stepnext -> D4 green     backplane_aux3     -> D2 red
-- The DS90LV048A fail-safe drives an OPEN / undriven pair HIGH, so an open pair = LED
-- lit and never changing. (bp_rx is the gated version that keeps open pairs dark.)

library ieee;
use ieee.std_logic_1164.all;

entity bp_rx_raw is
  port (
    backplane_sck, backplane_mosi, backplane_cs, backplane_stepnext : in std_logic;
    backplane_ramreset, backplane_aux1, backplane_aux2, backplane_aux3 : in std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of bp_rx_raw is
begin
  led_g1 <= not backplane_sck;
  led_g2 <= not backplane_mosi;
  led_g3 <= not backplane_cs;
  led_g4 <= not backplane_stepnext;
  led_g5 <= not backplane_ramreset;
  led_g6 <= not backplane_aux1;
  led_r1 <= not backplane_aux2;
  led_r2 <= not backplane_aux3;
  led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
