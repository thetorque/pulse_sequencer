-- led_blink.vhd
-- ECP5 DDS board bring-up, Phase-1 STEP 2: blink (on/off) using the internal
-- oscillator OSCG -- NO external clock needed.
-- Adds proof (on top of led_static) that the fabric clock runs and sequential
-- logic places/routes/runs: the 6 bicolor LEDs flip GREEN <-> RED at ~0.6 Hz.
--
-- LEDs are ACTIVE-LOW (common anode to P3.3V): '0' = ON, '1' = OFF.
--
-- OSCG: ECP5 internal oscillator, ~310 MHz nominal (wide tolerance ~+/-7%),
-- integer divider DIV = 2..128.  DIV=128 -> ~2.4 MHz fabric clock.  That is
-- plenty for a blink and has zero external-part dependency (ideal for first light).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_blink is
  port (
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of led_blink is

  -- ECP5 internal oscillator primitive (black-box; mapped by nextpnr-ecp5).
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  signal clk  : std_logic;
  signal cnt  : unsigned(20 downto 0) := (others => '0');  -- wraps ~ every 2^21
  signal tick : std_logic := '0';                          -- ~0.6 Hz square wave

begin

  osc_inst : OSCG
    generic map ( DIV => 128 )          -- ~310 MHz / 128 ~= 2.4 MHz
    port map   ( OSC => clk );

  -- Free-running counter; toggle 'tick' once per full wrap.
  -- 2^21 / 2.4 MHz ~= 0.87 s half-period -> full green/red cycle ~1.7 s.
  process(clk)
  begin
    if rising_edge(clk) then
      cnt <= cnt + 1;
      if cnt = 0 then
        tick <= not tick;
      end if;
    end if;
  end process;

  -- tick='0' -> greens ON, reds OFF ; tick='1' -> reds ON, greens OFF.
  led_g1 <= tick; led_g2 <= tick; led_g3 <= tick;
  led_g4 <= tick; led_g5 <= tick; led_g6 <= tick;

  led_r1 <= not tick; led_r2 <= not tick; led_r3 <= not tick;
  led_r4 <= not tick; led_r5 <= not tick; led_r6 <= not tick;

end architecture;
