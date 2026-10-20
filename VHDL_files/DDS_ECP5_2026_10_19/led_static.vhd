-- led_static.vhd
-- ECP5 DDS board bring-up, Phase-1 STEP 1: static LED test (NO clock).
-- Drives all 12 bicolor-LED cathodes LOW => every element ON (green+red = amber).
-- Proves: JTAG/openFPGALoader link, bitstream loads + DONE asserts, all 12 I/O
-- balls are bonded & soldered, LED+resistor network correct.  No clock involved,
-- so this is the safest first bitstream (synthesizes cleanly in any flow).
--
-- LEDs are ACTIVE-LOW (common anode to P3.3V): '0' = ON, '1' = OFF.

library ieee;
use ieee.std_logic_1164.all;

entity led_static is
  port (
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of led_static is
begin
  -- All elements ON (drive cathodes low). Tests all 12 pins at once.
  led_g1 <= '0'; led_g2 <= '0'; led_g3 <= '0';
  led_g4 <= '0'; led_g5 <= '0'; led_g6 <= '0';
  led_r1 <= '0'; led_r2 <= '0'; led_r3 <= '0';
  led_r4 <= '0'; led_r5 <= '0'; led_r6 <= '0';
end architecture;
