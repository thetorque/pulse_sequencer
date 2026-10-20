-- tb_ebr_test.vhd -- drive a small, fast ebr_test and confirm the PASS path:
-- after the self-test completes, the green LEDs must blink (pass) and the fail
-- red LEDs must stay off.  (Uses sim_oscg.vhd for the OSCG clock.)

library ieee;
use ieee.std_logic_1164.all;

entity tb_ebr_test is
end entity;

architecture sim of tb_ebr_test is
  signal dds_reset, dds_pwrdwn, rf_main_sw, vga_shdn : std_logic;
  signal led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : std_logic;
  signal led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : std_logic;
begin
  dut : entity work.ebr_test
    generic map ( AW => 5, HB => 4, POR_W => 4 )   -- 32 rows, fast heartbeat + POR
    port map ( dds_reset => dds_reset, dds_pwrdwn => dds_pwrdwn,
               rf_main_sw => rf_main_sw, vga_shdn => vga_shdn,
               led_g1 => led_g1, led_g2 => led_g2, led_g3 => led_g3,
               led_g4 => led_g4, led_g5 => led_g5, led_g6 => led_g6,
               led_r1 => led_r1, led_r2 => led_r2, led_r3 => led_r3,
               led_r4 => led_r4, led_r5 => led_r5, led_r6 => led_r6 );

  process
    variable g_on, g_off, r_fail : boolean := false;
  begin
    wait for 300 us;                     -- past write + verify + settle
    for i in 0 to 60 loop                -- observe several heartbeat periods
      wait for 5 us;
      if led_g1 = '0' then g_on  := true; end if;   -- green lit
      if led_g1 = '1' then g_off := true; end if;   -- green off
      if led_r1 = '0' then r_fail := true; end if;  -- fail red lit
    end loop;

    assert g_on and g_off
      report "FAIL: green LEDs not blinking -> PASS not indicated" severity error;
    assert not r_fail
      report "FAIL: fail red LED asserted -> a row mismatched" severity error;
    if g_on and g_off and not r_fail then
      report "PASS: ebr_test reports PASS (greens blink, no fail)" severity note;
    end if;
    std.env.stop;
  end process;
end architecture;
