-- led_chase.vhd -- running-light (Knight Rider) sweep to verify the ECP5
-- internal oscillator (OSCG) + sequential logic.
--
-- PORTS ARE PHYSICAL POSITION, LEFT -> RIGHT as mounted on the PCB.
-- The LEDs are physically mounted (left to right): D5 D4 D1 D2 D3 D6, so:
--   led_p1 = leftmost  = D5 green (ball N16)
--   led_p2             = D4 green (ball M16)
--   led_p3             = D1 green (ball L16)
--   led_p4             = D2 green (ball K16)
--   led_p5             = D3 green (ball J16)
--   led_p6 = rightmost = D6 green (ball G15)
-- (the led_pN -> ball mapping lives in dds_chase.lpf)
--
-- A single GREEN dot bounces led_p1 -> led_p6 -> led_p1 (~0.11 s/step), smoothly
-- left-to-right across the board. Active-low: '0' = ON, '1' = OFF.
-- Reds are left undriven (high-Z -> off).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_chase is
  port (
    led_p1, led_p2, led_p3, led_p4, led_p5, led_p6 : out std_logic
  );
end entity;

architecture rtl of led_chase is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  signal clk : std_logic;
  signal div : unsigned(17 downto 0) := (others => '0');  -- ~2^18/2.4MHz ~= 0.11 s/step
  signal pos : integer range 0 to 5 := 0;
  signal dir : std_logic := '0';                          -- '0' moving right, '1' moving left
begin

  osc_inst : OSCG
    generic map ( DIV => 128 )          -- ~310 MHz / 128 ~= 2.4 MHz
    port map   ( OSC => clk );

  process(clk)
  begin
    if rising_edge(clk) then
      div <= div + 1;
      if div = 0 then
        if dir = '0' then
          if pos = 5 then dir <= '1'; pos <= 4;
          else pos <= pos + 1; end if;
        else
          if pos = 0 then dir <= '0'; pos <= 1;
          else pos <= pos - 1; end if;
        end if;
      end if;
    end if;
  end process;

  -- light only the green at the current physical position
  led_p1 <= '0' when pos = 0 else '1';
  led_p2 <= '0' when pos = 1 else '1';
  led_p3 <= '0' when pos = 2 else '1';
  led_p4 <= '0' when pos = 3 else '1';
  led_p5 <= '0' when pos = 4 else '1';
  led_p6 <= '0' when pos = 5 else '1';
end architecture;
