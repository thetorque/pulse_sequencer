-- ad9912_idcheck.vhd -- READ-ONLY AD9912 register dump / identity check.
--
-- Reads back registers that have KNOWN, NON-ZERO power-up defaults (Table 12),
-- WITHOUT writing anything, and lights one LED per register whose readback matches
-- the datasheet default. The star is the read-only Part ID (0x0002 = 0x82): we cannot
-- have written it, so reading 0x82 is irrefutable proof we are genuinely reading the
-- chip's register file. Pure readback works clock-independently (proven), so this does
-- NOT need the DAC system clock -- it's a clean "is the chip truly alive & readable" test.
--
-- 3-WIRE SPI (default mode): SDIO bidirectional, driven for the instruction, released
-- to Hi-Z for the read data phase and sampled on SDIO (pin 63). SDO (pin 62) unused.
--
-- LEDs (active-low: lit = that register read back its expected value):
--   g1=0x0002(82 RO)  g2=0x0003(19 RO)  g3=0x0000(18)  g4=0x0020(12)  g5=0x0022(04)
--   g6=0x0200(05)     r1=0x040E(10)     r2=0x0100(30)  r3=0x0106(01)
--   r5 = ALL-PASS summary.  r6 = heartbeat.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_idcheck is
  port (
    dds_sclk : out   std_logic;
    dds_sdio : inout std_logic;
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_idcheck is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  -- {16-bit read instruction (R/W=1, W=00, addr), 8-bit expected default}
  type rom_t is array (natural range <>) of std_logic_vector(23 downto 0);
  constant RROM : rom_t := (
    x"800282",   -- 0x0002 Part ID   -> 0x82 (RO)
    x"800319",   -- 0x0003           -> 0x19 (RO)
    x"800018",   -- 0x0000 serialcfg -> 0x18
    x"802012",   -- 0x0020 N-divider -> 0x12
    x"802204",   -- 0x0022 PLL param -> 0x04
    x"820005",   -- 0x0200 HSTL drv  -> 0x05
    x"840E10",   -- 0x040E reserved  -> 0x10
    x"810030",   -- 0x0100 reserved  -> 0x30
    x"810601"    -- 0x0106 S-div/2   -> 0x01
  );
  constant NR : integer := RROM'length;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';
  signal trig_cnt  : unsigned(19 downto 0) := (others => '0');
  signal go        : std_logic := '0';

  type st_t is (IDLE, R_LOAD, R_TXLO, R_TXHI, R_RXLO, R_RXHI, R_CS, R_GAP, R_CMP, SHOW);
  signal st    : st_t := IDLE;
  signal sh    : std_logic_vector(23 downto 0) := (others => '0');
  signal cnt   : integer range 0 to 16 := 0;
  signal rxcnt : integer range 0 to 8  := 0;
  signal gapc  : integer range 0 to 7  := 0;
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
        ridx <= 0; pass <= (others => '0');
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1'; sdio_oe <= '1';
            if go = '1' then ridx <= 0; pass <= (others => '0'); st <= R_LOAD; end if;

          when R_LOAD =>
            sh <= RROM(ridx)(23 downto 8) & x"00";   -- 16-bit read instruction
            exp <= RROM(ridx)(7 downto 0);
            cnt <= 16; rxcnt <= 8; cap <= (others => '0');
            sdio_oe <= '1'; dds_csb <= '0'; st <= R_TXLO;
          when R_TXLO =>
            dds_sclk <= '0'; sdio_drv <= sh(23); st <= R_TXHI;
          when R_TXHI =>
            dds_sclk <= '1';
            if cnt = 1 then sdio_oe <= '0'; st <= R_RXLO;
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

  dds_ioupdate <= '0';
  dds_reset    <= rst;
  dds_pwrdwn   <= '0';

  led_g1 <= not rpass(0); led_g2 <= not rpass(1); led_g3 <= not rpass(2);
  led_g4 <= not rpass(3); led_g5 <= not rpass(4); led_g6 <= not rpass(5);
  led_r1 <= not rpass(6); led_r2 <= not rpass(7); led_r3 <= not rpass(8);
  led_r4 <= '1';
  led_r5 <= not (rpass(0) and rpass(1) and rpass(2) and rpass(3) and rpass(4)
                 and rpass(5) and rpass(6) and rpass(7) and rpass(8));
  led_r6 <= heartbeat;
end architecture;
