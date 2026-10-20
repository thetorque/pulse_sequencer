-- led_half.vhd -- distinctive pattern for SSPI config verification.
-- Lights ONLY D1, D2, D3 GREEN; D4-D6 and all reds OFF.
-- Active-low: '0' = element ON, '1' = OFF.
--   unconfigured -> all LEDs dark
--   this bitstream -> top-3 green only (unmistakable)

library ieee;
use ieee.std_logic_1164.all;

entity led_half is
  port (
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of led_half is
begin
  led_g1 <= '0'; led_g2 <= '0'; led_g3 <= '0';   -- D1-D3 green ON
  led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';   -- D4-D6 green OFF
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1';   -- all reds OFF
  led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
