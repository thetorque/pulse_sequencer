-- ad9912_finetune.vhd -- frequency-accuracy / fine-tuning test for a frequency counter.
--
-- SYSCLK = 1 GHz direct (PLL bypassed). Steps through 5 fixed tones, ~20 s each, then
-- repeats (~100 s loop). Lock the counter to the SYSCLK source's 10 MHz reference; the
-- output should then read exactly FTW * 1 GHz / 2^48 (FTW LSB = 3.55 uHz):
--   k=0  50 MHz            FTW 0x0CCCCCCCCCCD -> 50 000 000.000 000 7 Hz
--   k=1  50 MHz + 1 Hz     FTW 0x0CCCCCD11850 -> 50 000 001.000 000 8 Hz
--   k=2  50 MHz + 0.1 Hz   FTW 0x0CCCCCCD3AC0 -> 50 000 000.099 998 9 Hz
--   k=3  50 MHz + 0.01 Hz  FTW 0x0CCCCCCCD7CC -> 50 000 000.010 001 6 Hz
--   k=4  123.456789 MHz    FTW 0x1F9ADD373963 -> 123 456 788.999 998 7 Hz (exercises all FTW bytes)
-- Each step re-writes the full config (0x0010 = D0, DAC FSC = 0x200, FTW) and transfers it
-- with the 0x0005 register update plus an IO_UPDATE pin pulse. Level: VGA 0xB40 -> ~0 dBm
-- at 50 MHz on board 8 (~+2 dBm at 123 MHz).
--
-- LEDs (active-low): g1..g3 = step index k in binary (g1 = MSB).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_finetune is
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

architecture rtl of ad9912_finetune is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  type ftw_tab_t is array (natural range <>) of unsigned(47 downto 0);
  constant FTW_TAB : ftw_tab_t := (
    x"0CCCCCCCCCCD",   -- 50 MHz
    x"0CCCCCD11850",   -- 50 MHz + 1 Hz
    x"0CCCCCCD3AC0",   -- 50 MHz + 0.1 Hz
    x"0CCCCCCCD7CC",   -- 50 MHz + 0.01 Hz
    x"1F9ADD373963"    -- 123.456789 MHz
  );
  constant NSTEPS    : integer := FTW_TAB'length;
  constant STEP_CLKS : integer := 48_400_000;                       -- ~20 s @ ~2.42 MHz OSCG
  constant VGA_CODE  : std_logic_vector(11 downto 0) := x"B40";     -- ~0 dBm @ 50 MHz
  constant NWORDS    : integer := 10;

  signal clk : std_logic;
  signal por : unsigned(15 downto 0) := (others => '0');
  signal rst : std_logic := '1';

  signal step_cnt : integer range 0 to STEP_CLKS - 1 := 0;
  signal k        : integer range 0 to NSTEPS - 1 := 0;
  signal ftw      : unsigned(47 downto 0);
  signal started  : std_logic := '0';
  signal go       : std_logic := '0';

  type st_t is (IDLE, LOAD, BIT_LO, BIT_HI, CS_HI, GAP, UPD_HI, UPD_LO);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(23 downto 0) := (others => '0');
  signal cnt  : integer range 0 to 24 := 0;
  signal widx : integer range 0 to NWORDS - 1 := 0;
  signal gapc : integer range 0 to 7 := 0;
  signal word : std_logic_vector(23 downto 0);
  signal kv   : unsigned(2 downto 0);
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  ftw <= FTW_TAB(k);

  -- per-step write list: {16-bit instruction, 8-bit data}
  with widx select word <=
    x"0010D0"                                   when 0,   -- PLL bypassed, direct SYSCLK
    x"040C02"                                   when 1,   -- DAC FSC[9:8]  (0x200)
    x"040B00"                                   when 2,   -- DAC FSC[7:0]
    x"01A6" & std_logic_vector(ftw(7 downto 0))   when 3,
    x"01A7" & std_logic_vector(ftw(15 downto 8))  when 4,
    x"01A8" & std_logic_vector(ftw(23 downto 16)) when 5,
    x"01A9" & std_logic_vector(ftw(31 downto 24)) when 6,
    x"01AA" & std_logic_vector(ftw(39 downto 32)) when 7,
    x"01AB" & std_logic_vector(ftw(47 downto 40)) when 8,
    x"000501"                                   when others;  -- register update

  -- POR + step timer: program step 0 right after reset, then step every ~20 s
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      go <= '0';
      if rst = '1' then
        step_cnt <= 0; k <= 0; started <= '0';
      elsif started = '0' then
        started <= '1'; go <= '1';
      elsif step_cnt = STEP_CLKS - 1 then
        step_cnt <= 0; go <= '1';
        if k = NSTEPS - 1 then k <= 0; else k <= k + 1; end if;
      else
        step_cnt <= step_cnt + 1;
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
  rf_main_sw <= '1';

  kv <= to_unsigned(k, 3);
  led_g1 <= not kv(2); led_g2 <= not kv(1); led_g3 <= not kv(0);
  led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
