-- ad9912_quiet.vhd -- static board state for supply-current vs SYSCLK-frequency sweeps.
--
-- After POR, runs the ad9912_cfg sequence ONCE (PLL bypass 0x0010=D0, DAC FSC, FTW,
-- 0x0005 register update + IO_UPDATE pin pulse), then holds everything static: no
-- further SPI traffic, VGA DAC never written, RF switch fixed, ALL LEDs off. The only
-- thing left that can change the board current is the SYSCLK applied to the AD9912.
-- A clocked DDS core draws power that rises roughly in proportion to f_SYSCLK; an
-- unclocked core does not, so a current-vs-frequency sweep tests whether the core runs
-- without relying on SPI readback.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_quiet is
  port (
    dds_pwrdwn, dds_reset : out std_logic;
    dds_sclk, dds_sdio, dds_csb, dds_ioupdate : out std_logic;
    dds_sdo : in  std_logic;
    vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn : out std_logic;
    rf_main_sw : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_quiet is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;
  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal started   : std_logic := '0';
  signal start_cfg : std_logic := '0';
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  -- POR, then a single config pulse
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      start_cfg <= '0';
      if rst = '0' and started = '0' then
        started <= '1'; start_cfg <= '1';
      end if;
    end if;
  end process;

  u_cfg : entity work.ad9912_cfg
    generic map ( CDIV => 1 )
    port map ( clk => clk, rst => rst, start => start_cfg, busy => open,
               sclk => dds_sclk, sdio => dds_sdio, sdo => dds_sdo,
               csb => dds_csb, io_update => dds_ioupdate );

  dds_pwrdwn <= '0';        -- powered up
  dds_reset  <= rst;        -- POR pulse, then released

  -- downstream held constant: VGA DAC never written (deselected), RF switch fixed
  vga_cs <= '1'; vga_sck <= '0'; vga_sci <= '0'; vga_ldac <= '1'; vga_shdn <= '1';
  rf_main_sw <= '0';

  -- all LEDs OFF/static
  led_g1 <= '1'; led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
