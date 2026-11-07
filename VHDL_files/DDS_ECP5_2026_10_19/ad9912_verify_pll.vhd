-- ad9912_verify_pll.vhd -- full SPI write-then-readback VERIFY of the AD9912 config.
--
-- PLL-MODE VARIANT of ad9912_verify (generated from it; only 0x0010 differs):
-- 0x0010 = 0xC0 enables the SYSCLK PLL, so the DDS core is clocked by the internal VCO
-- (700-1000 MHz) instead of the direct SYSCLK path. Feed a 11-200 MHz reference (e.g.
-- 24 MHz -> x40 default multiplier -> 960 MHz). Even unlocked (LOOP_FILTER is just 1k to
-- GND on this board) the VCO runs, so if the FTW LEDs pass here but not in the direct-mode
-- build, the digital core is fine and the direct SYSCLK->core path is what's failing.
--
-- Writes the complete tone config, triggers a register update over SPI (0x0005=0x01),
-- then reads back EACH register and compares to the value written. One LED per
-- register lights when that word round-tripped correctly (written == read back).
-- This proves, byte by byte, that data reaches the DDS and reflects back.
--
-- 3-WIRE SPI (default mode, 0x0000 never touched): SDIO is bidirectional -- driven for
-- instruction/data, released to Hi-Z for the read data phase and sampled on SDIO
-- (pin 63). SDO (pin 62, confirmed open) is NOT used.
--
-- Register types matter for readback: a default read returns the ACTIVE register
-- (0x0004 bit0 = 0). 0x0010/0x040B/0x040C are live, so they read back immediately. The
-- FTW (0x01A6..0x01AB) is buffered: it only reads back here if the 0x0005 register
-- update actually transferred it to the active DDS, which needs a running DAC clock.
-- So the FTW LEDs test the update path end-to-end (buffer-read variant: add 0x0004=0x01).
--
-- LEDs (active-low: lit = match). FTW bytes are the 30 MHz @ 250 MHz word:
--   g1=0x0010(C0) g2=0x040C(03) g3=0x040B(FF) g4=0x01A6(1F) g5=0x01A7(85)
--   g6=0x01A8(EB) r1=0x01A9(51) r2=0x01AA(B8) r3=0x01AB(1E)
--   r5 = ALL-PASS summary (lit only if every register matched)
--   r6 = heartbeat.  All of g1..r3 + r5 lit => every word verified good.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_verify_pll is
  port (
    dds_sclk : out   std_logic;
    dds_sdio : inout std_logic;                      -- 3-wire: bidirectional
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_verify_pll is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  -- Config writes: {16-bit instruction, 8-bit data}. 0x0005=0x01 (update) is LAST.
  type rom_t is array (natural range <>) of std_logic_vector(23 downto 0);
  constant WROM : rom_t := (
    x"0010C0", x"040C03", x"040BFF",
    x"01A61F", x"01A785", x"01A8EB", x"01A951", x"01AAB8", x"01AB1E",
    x"000501"                                  -- register update over SPI (read ACTIVE regs)
  );
  -- Readback+expect: {16-bit read instruction, 8-bit expected}. One per verified reg.
  constant RROM : rom_t := (
    x"8010C0", x"840C03", x"840BFF",
    x"81A61F", x"81A785", x"81A8EB", x"81A951", x"81AAB8", x"81AB1E"
  );
  constant NW : integer := WROM'length;
  constant NR : integer := RROM'length;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';
  signal trig_cnt  : unsigned(19 downto 0) := (others => '0');
  signal go        : std_logic := '0';

  type st_t is (IDLE,
                W_LOAD, W_LO, W_HI, W_CS, W_GAP,
                R_LOAD, R_TXLO, R_TXHI, R_RXLO, R_RXHI, R_CS, R_GAP, R_CMP,
                SHOW);
  signal st    : st_t := IDLE;
  signal sh    : std_logic_vector(23 downto 0) := (others => '0');
  signal cnt   : integer range 0 to 24 := 0;
  signal rxcnt : integer range 0 to 8  := 0;
  signal gapc  : integer range 0 to 7  := 0;
  signal widx  : integer range 0 to NW := 0;
  signal ridx  : integer range 0 to NR := 0;
  signal cap   : std_logic_vector(7 downto 0) := (others => '0');
  signal exp   : std_logic_vector(7 downto 0) := (others => '0');
  signal pass  : std_logic_vector(NR-1 downto 0) := (others => '0');
  signal rpass : std_logic_vector(NR-1 downto 0) := (others => '0');

  signal sdio_drv : std_logic := '0';
  signal sdio_oe  : std_logic := '1';
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  dds_sdio <= sdio_drv when sdio_oe = '1' else 'Z';

  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  -- periodic re-run (~0.43 s)
  process(clk) begin
    if rising_edge(clk) then
      go <= '0';
      if rst = '1' then trig_cnt <= (others => '0');
      else
        trig_cnt <= trig_cnt + 1;
        if trig_cnt = (2**20 - 1) then go <= '1'; end if;
      end if;
    end if;
  end process;

  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; dds_sclk <= '0'; sdio_drv <= '0'; sdio_oe <= '1'; dds_csb <= '1';
        widx <= 0; ridx <= 0; pass <= (others => '0');
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1'; sdio_oe <= '1';
            if go = '1' then widx <= 0; ridx <= 0; pass <= (others => '0'); st <= W_LOAD; end if;

          -- ---- write phase ----
          when W_LOAD =>
            sh <= WROM(widx); cnt <= 24; sdio_oe <= '1'; dds_csb <= '0'; st <= W_LO;
          when W_LO =>
            dds_sclk <= '0'; sdio_drv <= sh(23); st <= W_HI;
          when W_HI =>
            dds_sclk <= '1';
            if cnt = 1 then st <= W_CS;
            else sh <= sh(22 downto 0) & '0'; cnt <= cnt - 1; st <= W_LO; end if;
          when W_CS =>
            dds_sclk <= '0'; dds_csb <= '1'; gapc <= 4; st <= W_GAP;
          when W_GAP =>
            if gapc = 0 then
              if widx = NW - 1 then st <= R_LOAD;
              else widx <= widx + 1; st <= W_LOAD; end if;
            else gapc <= gapc - 1; end if;

          -- ---- read-back + compare phase ----
          when R_LOAD =>
            sh <= RROM(ridx)(23 downto 8) & x"00";   -- 16-bit read instruction, left-justified
            exp <= RROM(ridx)(7 downto 0);
            cnt <= 16; rxcnt <= 8; cap <= (others => '0');
            sdio_oe <= '1'; dds_csb <= '0'; st <= R_TXLO;
          when R_TXLO =>
            dds_sclk <= '0'; sdio_drv <= sh(23); st <= R_TXHI;
          when R_TXHI =>
            dds_sclk <= '1';
            if cnt = 1 then sdio_oe <= '0'; st <= R_RXLO;   -- release SDIO for read
            else sh <= sh(22 downto 0) & '0'; cnt <= cnt - 1; st <= R_TXLO; end if;
          when R_RXLO =>
            dds_sclk <= '0'; st <= R_RXHI;
          when R_RXHI =>
            dds_sclk <= '1'; cap <= cap(6 downto 0) & dds_sdio;
            if rxcnt = 1 then st <= R_CS; else rxcnt <= rxcnt - 1; st <= R_RXLO; end if;
          when R_CS =>
            dds_sclk <= '0'; dds_csb <= '1'; sdio_oe <= '1'; gapc <= 4; st <= R_GAP;
          when R_GAP =>
            if gapc = 0 then st <= R_CMP; else gapc <= gapc - 1; end if;
          when R_CMP =>
            if cap = exp then pass(ridx) <= '1'; else pass(ridx) <= '0'; end if;
            if ridx = NR - 1 then st <= SHOW;
            else ridx <= ridx + 1; st <= R_LOAD; end if;

          when SHOW =>
            rpass <= pass; st <= IDLE;
        end case;
      end if;
    end if;
  end process;

  dds_ioupdate <= '0';          -- update done over SPI (0x0005), pin not relied on
  dds_reset    <= rst;
  dds_pwrdwn   <= '0';

  -- one LED per register: lit (active-low) when readback matched the written value
  led_g1 <= not rpass(0); led_g2 <= not rpass(1); led_g3 <= not rpass(2);
  led_g4 <= not rpass(3); led_g5 <= not rpass(4); led_g6 <= not rpass(5);
  led_r1 <= not rpass(6); led_r2 <= not rpass(7); led_r3 <= not rpass(8);
  led_r4 <= '1';
  led_r5 <= not (rpass(0) and rpass(1) and rpass(2) and rpass(3) and rpass(4)
                 and rpass(5) and rpass(6) and rpass(7) and rpass(8));  -- ALL-PASS
  led_r6 <= heartbeat;
end architecture;
