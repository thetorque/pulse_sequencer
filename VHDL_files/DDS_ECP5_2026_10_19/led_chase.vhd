-- led_chase.vhd -- colour-cycling running light (verifies ECP5 OSCG + logic).
-- A single dot sweeps LEFT -> RIGHT across the board, one colour per pass:
--   pass 1 GREEN, pass 2 RED, pass 3 AMBER (green+red), then repeat.
--
-- PORTS ARE PHYSICAL POSITION, LEFT -> RIGHT as mounted on the PCB.
-- LEDs are mounted (left to right): D5 D4 D1 D2 D3 D6, so:
--   pos  physical  green ball  red ball
--   led_p1 = D5      N16         M15   (leftmost)
--   led_p2 = D4      M16         L15
--   led_p3 = D1      L16         K15
--   led_p4 = D2      K16         J15
--   led_p5 = D3      J16         H15
--   led_p6 = D6      G15         G16   (rightmost)
-- (the led_pgN/led_prN -> ball mapping lives in dds_chase.lpf)
--
-- Active-low: '0' = element ON, '1' = OFF.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_chase is
  port (
    -- green cathodes, physical left -> right
    led_pg1, led_pg2, led_pg3, led_pg4, led_pg5, led_pg6 : out std_logic;
    -- red cathodes, physical left -> right
    led_pr1, led_pr2, led_pr3, led_pr4, led_pr5, led_pr6 : out std_logic
  );
end entity;

architecture rtl of led_chase is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  signal clk   : std_logic;
  signal div   : unsigned(17 downto 0) := (others => '0');  -- ~0.11 s/step
  signal pos   : integer range 0 to 5 := 0;                 -- dot position (0=left)
  signal color : integer range 0 to 2 := 0;                 -- 0 green, 1 red, 2 amber

  signal g : std_logic := '0';   -- green active this pass?
  signal r : std_logic := '0';   -- red active this pass?
begin

  osc_inst : OSCG
    generic map ( DIV => 128 )          -- ~310 MHz / 128 ~= 2.4 MHz
    port map   ( OSC => clk );

  -- advance: step the dot left->right; at the right end wrap and change colour
  process(clk)
  begin
    if rising_edge(clk) then
      div <= div + 1;
      if div = 0 then
        if pos = 5 then
          pos <= 0;
          if color = 2 then color <= 0; else color <= color + 1; end if;
        else
          pos <= pos + 1;
        end if;
      end if;
    end if;
  end process;

  g <= '1' when (color = 0 or color = 2) else '0';   -- green on for green/amber
  r <= '1' when (color = 1 or color = 2) else '0';   -- red   on for red/amber

  -- light the active colour(s) at the current position only (active-low)
  led_pg1 <= '0' when (pos = 0 and g = '1') else '1';
  led_pg2 <= '0' when (pos = 1 and g = '1') else '1';
  led_pg3 <= '0' when (pos = 2 and g = '1') else '1';
  led_pg4 <= '0' when (pos = 3 and g = '1') else '1';
  led_pg5 <= '0' when (pos = 4 and g = '1') else '1';
  led_pg6 <= '0' when (pos = 5 and g = '1') else '1';

  led_pr1 <= '0' when (pos = 0 and r = '1') else '1';
  led_pr2 <= '0' when (pos = 1 and r = '1') else '1';
  led_pr3 <= '0' when (pos = 2 and r = '1') else '1';
  led_pr4 <= '0' when (pos = 3 and r = '1') else '1';
  led_pr5 <= '0' when (pos = 4 and r = '1') else '1';
  led_pr6 <= '0' when (pos = 5 and r = '1') else '1';
end architecture;
