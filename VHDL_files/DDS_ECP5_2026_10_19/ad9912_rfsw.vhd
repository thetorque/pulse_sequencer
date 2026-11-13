-- ad9912_rfsw.vhd -- RF switch (PE4251, rf_main_sw) isolation test.
--
-- Fixed 50 MHz tone at 1 GHz SYSCLK, VGA 0xB40 (~0 dBm on board 8), DAC FSC 0x200.
-- The RF switch toggles every ~10 s: ON (rf_main_sw = 1) / OFF (rf_main_sw = 0).
-- Measure the output level in both states: isolation = P_on - P_off.
-- Compare with the minimum-VGA level (VGA 0x000 + FSC 0x000 = -49.8 dBm on board 8),
-- i.e. the legacy "off = -37 dBm" approach. (DDS_BUS_CONTRACT.md: CTRL.RF_ON.)
-- To test another frequency, change FTW below (FTW = round(f/1 GHz * 2^48)).
--
-- LEDs (active-low): g1 lit = RF switch ON, r1 lit = RF switch OFF;
--                    g6 flashes at each ~2 s config refresh.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_rfsw is
  port (
    dds_sclk, dds_sdio : out std_logic;
    dds_sdo            : in  std_logic;
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn : out std_logic;
    rf_main_sw : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_rfsw is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  constant FTW       : unsigned(47 downto 0) := x"0CCCCCCCCCCD";      -- 50 MHz @ 1 GHz
  constant VGA_CODE  : std_logic_vector(11 downto 0) := x"B40";      -- ~0 dBm (board 8)
  constant STEP_CLKS : integer := 4_840_000;                         -- ~2 s @ ~2.42 MHz OSCG
  constant NWORDS    : integer := 10;

  signal clk : std_logic;
  signal por : unsigned(15 downto 0) := (others => '0');
  signal rst : std_logic := '1';

  signal step_cnt : integer range 0 to STEP_CLKS - 1 := 0;
  signal started  : std_logic := '0';
  signal go       : std_logic := '0';
  signal blink    : integer range 0 to 255_000 := 0;
  signal sw_cnt   : integer range 0 to 24_200_000 := 0;               -- ~10 s @ ~2.42 MHz
  signal sw_on    : std_logic := '1';

  type st_t is (IDLE, LOAD, BIT_LO, BIT_HI, CS_HI, GAP, UPD_HI, UPD_LO);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(23 downto 0) := (others => '0');
  signal cnt  : integer range 0 to 24 := 0;
  signal widx : integer range 0 to NWORDS - 1 := 0;
  signal gapc : integer range 0 to 7 := 0;
  signal word : std_logic_vector(23 downto 0);
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  -- write list: {16-bit instruction, 8-bit data}
  with widx select word <=
    x"0010D0"                                   when 0,   -- PLL bypassed, direct SYSCLK
    x"040C02"                                   when 1,   -- DAC FSC[9:8]  (0x200)
    x"040B00"                                   when 2,   -- DAC FSC[7:0]
    x"01A6" & std_logic_vector(FTW(7 downto 0))   when 3,
    x"01A7" & std_logic_vector(FTW(15 downto 8))  when 4,
    x"01A8" & std_logic_vector(FTW(23 downto 16)) when 5,
    x"01A9" & std_logic_vector(FTW(31 downto 24)) when 6,
    x"01AA" & std_logic_vector(FTW(39 downto 32)) when 7,
    x"01AB" & std_logic_vector(FTW(47 downto 40)) when 8,
    x"000501"                                   when others;  -- register update

  -- POR + refresh timer
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      go <= '0';
      if rst = '1' then
        step_cnt <= 0; started <= '0'; blink <= 0;
      else
        if blink /= 0 then blink <= blink - 1; end if;
        if sw_cnt = 24_200_000 then sw_cnt <= 0; sw_on <= not sw_on; else sw_cnt <= sw_cnt + 1; end if;
        if started = '0' then
          started <= '1'; go <= '1'; blink <= 255_000;
        elsif step_cnt = STEP_CLKS - 1 then
          step_cnt <= 0; go <= '1'; blink <= 255_000;
        else
          step_cnt <= step_cnt + 1;
        end if;
      end if;
    end if;
  end process;

  -- SPI writer: one CSB cycle per word, then an IO_UPDATE pin pulse
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; dds_sclk <= '0'; dds_sdio <= '0'; dds_csb <= '1'; dds_ioupdate <= '0';
        widx <= 0;
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1'; dds_ioupdate <= '0';
            if go = '1' then widx <= 0; st <= LOAD; end if;
          when LOAD =>
            sh <= word; cnt <= 24; dds_csb <= '0'; st <= BIT_LO;
          when BIT_LO =>
            dds_sclk <= '0'; dds_sdio <= sh(23); st <= BIT_HI;
          when BIT_HI =>
            dds_sclk <= '1';
            if cnt = 1 then st <= CS_HI;
            else sh <= sh(22 downto 0) & '0'; cnt <= cnt - 1; st <= BIT_LO; end if;
          when CS_HI =>
            dds_sclk <= '0'; dds_csb <= '1'; gapc <= 4; st <= GAP;
          when GAP =>
            if gapc = 0 then
              if widx = NWORDS - 1 then gapc <= 7; st <= UPD_HI;
              else widx <= widx + 1; st <= LOAD; end if;
            else gapc <= gapc - 1; end if;
          when UPD_HI =>
            dds_ioupdate <= '1';
            if gapc = 0 then st <= UPD_LO; else gapc <= gapc - 1; end if;
          when UPD_LO =>
            dds_ioupdate <= '0'; st <= IDLE;
        end case;
      end if;
    end if;
  end process;

  u_dac : entity work.dac_spi
    port map ( clk => clk, rst => rst, start => go, code => VGA_CODE,
               busy => open, sck => vga_sck, sdi => vga_sci,
               cs => vga_cs, ldac => vga_ldac );

  dds_reset  <= rst;
  dds_pwrdwn <= '0';
  vga_shdn   <= '1';
  rf_main_sw <= sw_on;

  led_g1 <= not sw_on;                            -- lit = RF ON
  led_g6 <= '0' when blink /= 0 else '1';         -- ~0.1 s flash at each refresh
  led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1';
  led_r1 <= sw_on;                                -- lit = RF OFF
  led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
