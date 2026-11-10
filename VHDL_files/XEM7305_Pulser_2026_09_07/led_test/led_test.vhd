-- led_test.vhd -- master FPGA board (XEM7305 carrier) status-LED check, D4..D11.
--
-- Standalone: no FrontPanel endpoints, no external clock. Clocked from the
-- 7-series configuration oscillator (STARTUPE2 CFGMCLK, ~65 MHz nominal, +-50 %),
-- so it only depends on the LED pins themselves.
--
-- Pattern (repeats, ~6 s): walk a single lit LED D4 -> D11 (~0.5 s each),
-- then all 8 on (~1 s), then all off (~1 s).
-- LEDs are active-HIGH (FPGA pin -> 4k7 -> LED anode, cathode to GND).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library unisim;
use unisim.vcomponents.all;

entity led_test is
  port ( led_out : out std_logic_vector(7 downto 0) );
end entity;

architecture rtl of led_test is
  signal clk  : std_logic;
  signal tick : unsigned(24 downto 0) := (others => '0');   -- 2^25 / 65 MHz ~ 0.52 s
  signal step : unsigned(3 downto 0)  := (others => '0');   -- 0..7 walk, 8-9 all on, 10-11 off
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
        if step = 11 then step <= (others => '0'); else step <= step + 1; end if;
      end if;
    end if;
  end process;

  process(step) begin
    if step < 8 then
      led_out <= (others => '0');
      led_out(to_integer(step(2 downto 0))) <= '1';
    elsif step < 10 then
      led_out <= (others => '1');
    else
      led_out <= (others => '0');
    end if;
  end process;
end architecture;
