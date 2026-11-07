-- ad9912_rb3.vhd -- AD9912 SPI READBACK diagnostic, 3-WIRE (SDIO bidirectional).
--
-- Why this exists: the old ad9912_rb used 4-WIRE mode (wrote 0x0000=0x01, read on
-- dds_sdo / pin 62) and returned 0x00. That bundled TWO possible causes: (a) no
-- DAC system clock, or (b) a bad SDO (pin 62) joint/trace. This test removes SDO
-- from the picture: the AD9912 powers up in 3-WIRE mode by default (0x0000 bit0=0),
-- where read data comes back on SDIO (pin 63) -- the SAME line we write on, which
-- is known good. Per the datasheet, "all serial port operations depend on the
-- presence of the DAC system clock", so:
--   * reads back 0xD0  -> core IS clocked AND SPI fully works -> fault is the
--                         DAC-output/RF path (R46, pins 50/51); old 0x00 = SDO line.
--   * reads back 0x00  -> no system clock at the core -> it's the clock drive.
--
-- Sequence (repeats ~4x/s), 0x0000 is NEVER touched (stays 3-wire default):
--   1. write 0x040B = 0x5A   -> DISTINCTIVE, non-default value in a LIVE register
--                               (DAC full-scale current, default 0xFF). MUST be a LIVE
--                               reg: buffered/mirrored (M) regs like FTW/POW need an
--                               IO_UPDATE to transfer buffer->active, and the default
--                               read returns the ACTIVE reg -- so a buffered reg reads
--                               its default here regardless of the write. 0x040B is
--                               live, so write takes effect immediately, no IO_UPDATE.
--   2. read  0x040B          -> instruction 0x840B (16 bits, SDIO driven), then
--                               release SDIO to Hi-Z and read 8 data bits on SDIO.
-- Expect 0x5A = 0101_1010 -> g2,g4,g5,r1 lit. Reading 0x5A => SPI WRITE+READ both
-- genuinely work. 0xFF (all data LEDs lit) => write did NOT land (read is default).
-- 0x00 (all dark) => read path dead.
-- SPI: mode 0, MSB-first. Our write bits are sampled by the AD9912 on SCLK rising
-- edge; the AD9912 launches read bits on SCLK falling edge (tDV<=11 ns), so we
-- sample SDIO on the following SCLK rising edge.
--
-- LEDs (active-low): g1=bit7 g2=bit6 g3=bit5 g4=bit4 g5=bit3 g6=bit2 r1=bit1 r2=bit0,
-- r6=heartbeat. Expect 0xD0 = 1101_0000 -> g1,g2,g4 lit, rest dark.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_rb3 is
  port (
    dds_sclk : out   std_logic;
    dds_sdio : inout std_logic;                      -- 3-wire: bidirectional
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_rb3 is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';
  signal trig_cnt  : unsigned(18 downto 0) := (others => '0');
  signal go        : std_logic := '0';

  type st_t is (IDLE, LOAD, TX_LO, TX_HI, RX_LO, RX_HI, CS_HI, GAP, FIN);
  signal st     : st_t := IDLE;
  signal cmd    : integer range 0 to 2 := 0;
  signal sh     : std_logic_vector(23 downto 0) := (others => '0'); -- left-justified tx
  signal txcnt  : integer range 0 to 24 := 0;
  signal rxcnt  : integer range 0 to 8  := 0;
  signal gapc   : integer range 0 to 7  := 0;
  signal cap    : std_logic_vector(7 downto 0) := (others => '0');
  signal result : std_logic_vector(7 downto 0) := (others => '0');

  signal sdio_drv : std_logic := '0';   -- value we drive onto SDIO
  signal sdio_oe  : std_logic := '1';   -- 1 = drive, 0 = release (Hi-Z, chip drives)
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  -- bidirectional SDIO: drive when oe=1, release to Hi-Z when oe=0 (read phase)
  dds_sdio <= sdio_drv when sdio_oe = '1' else 'Z';

  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  -- periodic trigger (~0.22 s)
  process(clk) begin
    if rising_edge(clk) then
      go <= '0';
      if rst = '1' then trig_cnt <= (others => '0');
      else
        trig_cnt <= trig_cnt + 1;
        if trig_cnt = (2**19 - 1) then go <= '1'; end if;
      end if;
    end if;
  end process;

  -- SPI command sequencer
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; dds_sclk <= '0'; sdio_drv <= '0'; sdio_oe <= '1'; dds_csb <= '1';
        cmd <= 0; cap <= (others => '0');
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1'; sdio_oe <= '1';
            if go = '1' then cmd <= 0; st <= LOAD; end if;

          when LOAD =>
            cap <= (others => '0');
            sdio_oe <= '1';
            case cmd is
              when 0      => sh <= x"040B5A"; txcnt <= 24; rxcnt <= 0;  -- write 0x040B=0x5A (DAC FSC, LIVE reg, default 0xFF)
              when others => sh <= x"840B00"; txcnt <= 16; rxcnt <= 8;  -- read 0x040B
            end case;
            dds_csb <= '0';
            st <= TX_LO;

          when TX_LO =>                       -- present MSB while clock low
            dds_sclk <= '0';
            sdio_drv <= sh(23);
            st <= TX_HI;

          when TX_HI =>                       -- rising edge: AD9912 samples our bit
            dds_sclk <= '1';
            if txcnt = 1 then
              if rxcnt > 0 then
                sdio_oe <= '0';               -- release SDIO before the chip drives it
                st <= RX_LO;
              else
                st <= CS_HI;
              end if;
            else
              sh <= sh(22 downto 0) & '0';
              txcnt <= txcnt - 1;
              st <= TX_LO;
            end if;

          when RX_LO =>                       -- falling edge: AD9912 launches read bit
            dds_sclk <= '0';
            st <= RX_HI;

          when RX_HI =>                       -- rising edge: sample read bit on SDIO
            dds_sclk <= '1';
            cap <= cap(6 downto 0) & dds_sdio;
            if rxcnt = 1 then st <= CS_HI; else rxcnt <= rxcnt - 1; st <= RX_LO; end if;

          when CS_HI =>
            dds_sclk <= '0'; dds_csb <= '1'; sdio_oe <= '1'; gapc <= 4; st <= GAP;

          when GAP =>
            if gapc = 0 then
              if cmd = 1 then st <= FIN; else cmd <= cmd + 1; st <= LOAD; end if;
            else gapc <= gapc - 1; end if;

          when FIN =>
            result <= cap;                    -- latch the read-back byte
            st <= IDLE;
        end case;
      end if;
    end if;
  end process;

  dds_ioupdate <= '0';
  dds_reset    <= rst;    -- reset pulse during POR, then released
  dds_pwrdwn   <= '0';

  -- show the captured byte (active-low), heartbeat on r6
  led_g1 <= not result(7); led_g2 <= not result(6); led_g3 <= not result(5);
  led_g4 <= not result(4); led_g5 <= not result(3); led_g6 <= not result(2);
  led_r1 <= not result(1); led_r2 <= not result(0);
  led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1';
  led_r6 <= heartbeat;
end architecture;
