-- ad9912_test.vhd -- AD9912 first-light bring-up: emit a single fixed tone and
-- route it out the board RF SMA for a scope.
--
-- Sequence after power-up:
--   * POR (~27 ms): hold AD9912 in hard reset (dds_reset high), SPI idle.
--   * after reset release, every ~0.2 s re-issue:
--       - MCP4821 DAC  <- VGA gain code (sets ADL5330 gain via R48/R49 divider)
--       - AD9912       <- FTW (POW=0) + IO_UPDATE strobe  -> steady tone
--   * rf_main_sw = ON so the tone reaches the RF output SMA.
--
-- Tone: the full init + FTW lives in ad9912_cfg's ROM (PLL bypass, DAC full-scale,
-- FTW = round(f_out/f_sysclk * 2^48), 0x0005 update + IO_UPDATE pin pulse); retune
-- there. LEDs: g6 = heartbeat (alive), g1 = lit once a tone has been issued.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_test is
  port (
    -- AD9912 4-wire SPI + control
    dds_sclk, dds_sdio : out std_logic;
    dds_sdo            : in  std_logic;
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    -- MCP4821 amplitude DAC (sets ADL5330 VGA gain)
    vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn : out std_logic;
    -- main RF switch to the output SMA
    rf_main_sw : out std_logic;
    -- all status LEDs (declared so none float)
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_test is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  -- MCP4821 code -> VOUT = 2.048 V * code/4096 -> R48/R49 divider (x0.683) -> ADL5330 GAIN.
  -- ADL5330 gain ~= (V_GAIN - 0.88 V) / 20.7 mV/dB: 0x960 -> 0.82 V (-3 dB),
  -- 0xA11 -> 0 dB, 0xC6F -> +10 dB, 0xECD -> +20 dB, 0xFFF -> 1.40 V (max, +23 dB).
  constant VGA_CODE : std_logic_vector(11 downto 0) := x"000";          -- VGA minimum gain (~-35 dB)

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';

  signal refresh   : unsigned(18 downto 0) := (others => '0'); -- ~0.22 s @ 2.4 MHz
  signal start_dds : std_logic := '0';
  signal start_dac : std_logic := '0';
  signal programmed: std_logic := '0';
begin

  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  -- power-on reset
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
    end if;
  end process;

  -- heartbeat
  process(clk) begin
    if rising_edge(clk) then
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  -- periodic re-issue of the tone + VGA gain (first pulse ~0.22 s after reset,
  -- giving the AD9912 ample post-reset settle time)
  process(clk) begin
    if rising_edge(clk) then
      start_dds <= '0';
      start_dac <= '0';
      if rst = '1' then
        refresh <= (others => '0');
        programmed <= '0';
      else
        refresh <= refresh + 1;
        if refresh = (2**19 - 1) then
          start_dds  <= '1';
          start_dac  <= '1';
          programmed <= '1';
        end if;
      end if;
    end if;
  end process;

  u_dds : entity work.ad9912_cfg
    generic map ( CDIV => 64 )          -- SCLK ~19 kHz (clk/128) for easy scoping
    port map ( clk => clk, rst => rst, start => start_dds, busy => open,
               sclk => dds_sclk, sdio => dds_sdio, sdo => dds_sdo,
               csb => dds_csb, io_update => dds_ioupdate );

  u_dac : entity work.dac_spi
    port map ( clk => clk, rst => rst, start => start_dac, code => VGA_CODE,
               busy => open, sck => vga_sck, sdi => vga_sci,
               cs => vga_cs, ldac => vga_ldac );

  -- control / safe levels
  dds_reset  <= rst;     -- reset pulse during POR, then released
  dds_pwrdwn <= '0';     -- powered up
  vga_shdn   <= '1';     -- MCP4821 active
  rf_main_sw <= '1';     -- RF path ON -> tone reaches the output SMA

  -- LEDs (active-low: '0' = lit)
  led_g6 <= heartbeat;        -- alive
  led_g1 <= not programmed;   -- lit once a tone has been issued
  led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1';
  led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
