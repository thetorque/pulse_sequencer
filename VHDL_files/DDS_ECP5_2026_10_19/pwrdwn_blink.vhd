-- pwrdwn_blink.vhd -- toggle DDS_PWRDWN (AD9912 pin 58) at ~0.5 Hz for probing.
--
-- dds_pwrdwn: square wave, ~1 s high / ~1 s low (0.5 Hz), from the OSCG clock
-- (~2.42 MHz at DIV=128; OSCG tolerance ~+/-10% so the rate is approximate).
-- Other AD9912 control pins are held safe/idle so the toggle is the only change:
--   dds_reset = 0 (not reset), dds_csb = 1 (deselected), SPI outputs idle.
-- ALL LEDs held OFF (static) so their switching current doesn't disturb the
-- board current measurement.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pwrdwn_blink is
  port (
    dds_pwrdwn : out std_logic;
    dds_reset, dds_csb, dds_sclk, dds_sdio, dds_ioupdate : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of pwrdwn_blink is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;
  constant TOG : integer := 2_420_000;          -- ~1 s @ ~2.42 MHz -> 0.5 Hz square
  signal clk    : std_logic;
  signal cnt    : unsigned(22 downto 0) := (others => '0');
  signal pwr    : std_logic := '0';
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  process(clk) begin
    if rising_edge(clk) then
      if cnt >= TOG then cnt <= (others => '0'); pwr <= not pwr;
      else cnt <= cnt + 1; end if;
    end if;
  end process;

  dds_pwrdwn   <= pwr;      -- the 0.5 Hz blink (active-high: 1 = powered down)
  dds_reset    <= '0';      -- not in reset
  dds_csb      <= '1';      -- deselected
  dds_sclk     <= '0';
  dds_sdio     <= '0';
  dds_ioupdate <= '0';

  -- ALL LEDs OFF and static (active-low: '1' = off) so none switch during the
  -- current measurement
  led_g1 <= '1'; led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
