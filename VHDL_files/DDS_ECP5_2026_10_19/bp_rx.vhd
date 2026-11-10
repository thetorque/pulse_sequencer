-- bp_rx.vhd -- backplane link test, DDS-board side (receiver mirror).
--
-- Shows each of the 8 backplane lines (pulser -> DS90LV047A -> DIN41612 -> DS90LV048A ->
-- ECP5) on a status LED:
--   backplane_sck       -> D1 green      backplane_ramreset -> D5 green
--   backplane_mosi      -> D2 green      backplane_aux1     -> D6 green
--   backplane_cs        -> D3 green      backplane_aux2     -> D1 red
--   backplane_stepnext  -> D4 green      backplane_aux3     -> D2 red
-- D3..D6 red stay off.
--
-- The DS90LV048A has open-input fail-safe: an UNDRIVEN / unplugged pair reads a constant
-- HIGH. To make an open line visibly different from a live one, a line's LED only follows
-- the line while that line has been seen LOW within the last ~3.5 s ("alive"); a line
-- stuck high (open / fail-safe) stays DARK. So with the master's bp_test running:
--   live pair    -> LED blinks in step with the master's LED (lit when the line is high)
--   open pair    -> LED dark
--   inverted pair-> LED lit except during its own walk step
-- Pair with the master's bp_test (walks one line at a time, in the same order as the
-- master board's D4..D11, then all high ~1 s, then all low ~2 s).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bp_rx is
  port (
    backplane_sck, backplane_mosi, backplane_cs, backplane_stepnext : in std_logic;
    backplane_ramreset, backplane_aux1, backplane_aux2, backplane_aux3 : in std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of bp_rx is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  constant HOLD : integer := 8_500_000;                -- ~3.5 s @ ~2.42 MHz OSCG
  type cnt_arr is array (0 to 7) of integer range 0 to HOLD;

  signal clk   : std_logic;
  signal raw   : std_logic_vector(7 downto 0);
  signal s1, s2: std_logic_vector(7 downto 0) := (others => '1');
  signal alive : cnt_arr := (others => 0);             -- >0 = seen low recently
  signal on_v  : std_logic_vector(7 downto 0);
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  raw <= backplane_aux3 & backplane_aux2 & backplane_aux1 & backplane_ramreset &
         backplane_stepnext & backplane_cs & backplane_mosi & backplane_sck;

  process(clk) begin
    if rising_edge(clk) then
      s1 <= raw; s2 <= s1;                             -- 2-FF synchronizer
      for i in 0 to 7 loop
        if s2(i) = '0' then alive(i) <= HOLD;
        elsif alive(i) /= 0 then alive(i) <= alive(i) - 1; end if;
      end loop;
    end if;
  end process;

  gen : for i in 0 to 7 generate
    on_v(i) <= s2(i) when alive(i) /= 0 else '0';
  end generate;

  -- LEDs are active-low
  led_g1 <= not on_v(0);  led_g2 <= not on_v(1);  led_g3 <= not on_v(2);
  led_g4 <= not on_v(3);  led_g5 <= not on_v(4);  led_g6 <= not on_v(5);
  led_r1 <= not on_v(6);  led_r2 <= not on_v(7);
  led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
