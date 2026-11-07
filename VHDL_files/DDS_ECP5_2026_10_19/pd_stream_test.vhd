-- pd_stream_test.vhd -- AD9912 power-down current test WITH config streaming.
--
-- Purpose: decide whether toggling PWRDWN changes the board current when the
-- chip is actively configured (PLL-bypass + FTW + IO_UPDATE). A current step in
-- sync with the 0.5 Hz PWRDWN toggle => the AD9912 is drawing real (clocking)
-- current; no step => the core isn't being clocked, even when configured.
--
-- Controls so ONLY PWRDWN varies:
--   * ad9912_cfg is re-streamed continuously (~4-5x/s) regardless of PWRDWN, so
--     its SPI switching current is a CONSTANT offset (not correlated with the
--     toggle). When powered up, the config/FTW take effect; when powered down,
--     the writes are ignored.
--   * The downstream VGA (MCP4821) and RF switch are held FIXED/idle the whole
--     time -- no writes, deselected, constant level -- so they don't move.
--   * All LEDs held OFF (static) so they add no switching current.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pd_stream_test is
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

architecture rtl of pd_stream_test is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;
  constant TOG : integer := 2_420_000;          -- ~1 s @ ~2.42 MHz -> 0.5 Hz PWRDWN square
  signal clk     : std_logic;
  signal por     : unsigned(15 downto 0) := (others => '0');
  signal rst     : std_logic := '1';
  signal cnt     : unsigned(22 downto 0) := (others => '0');
  signal pwr     : std_logic := '0';
  signal refresh : unsigned(18 downto 0) := (others => '0');
  signal start_cfg : std_logic := '0';
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;

      -- 0.5 Hz PWRDWN toggle (the only intended variable)
      if cnt >= TOG then cnt <= (others => '0'); pwr <= not pwr;
      else cnt <= cnt + 1; end if;

      -- continuous config re-stream, independent of PWRDWN (constant SPI current)
      start_cfg <= '0';
      if rst = '1' then refresh <= (others => '0');
      else
        refresh <= refresh + 1;
        if refresh = (2**19 - 1) then start_cfg <= '1'; end if;
      end if;
    end if;
  end process;

  u_cfg : entity work.ad9912_cfg
    generic map ( CDIV => 1 )
    port map ( clk => clk, rst => rst, start => start_cfg, busy => open,
               sclk => dds_sclk, sdio => dds_sdio, sdo => dds_sdo,
               csb => dds_csb, io_update => dds_ioupdate );

  dds_pwrdwn <= pwr;        -- 0.5 Hz toggle
  dds_reset  <= rst;        -- POR pulse, then held low (not reset)

  -- downstream held CONSTANT throughout: VGA DAC never written (deselected,
  -- idle -> holds its power-on level), RF switch fixed
  vga_cs <= '1'; vga_sck <= '0'; vga_sci <= '0'; vga_ldac <= '1'; vga_shdn <= '1';
  rf_main_sw <= '0';

  -- all LEDs OFF/static
  led_g1 <= '1'; led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
