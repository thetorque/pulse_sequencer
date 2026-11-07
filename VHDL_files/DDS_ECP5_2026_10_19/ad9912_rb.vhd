-- ad9912_rb.vhd -- AD9912 SPI READBACK diagnostic.
--
-- Purpose: decide whether the dds_* SPI link + the AD9912 are actually alive,
-- since the dds_* SPI path has never been hardware-verified and the scope is
-- flat. Per the datasheet, "all serial port operations depend on the presence
-- of the DAC system clock", so a correct readback also proves the 400 MHz
-- clock is reaching the chip.
--
-- Sequence (repeats ~4x/s):
--   1. write 0x0000 = 0x01   -> SDO active (4-wire), read data comes on dds_sdo
--   2. write 0x0010 = 0xD0   -> a known value to read back
--   3. read  0x0010          -> instruction 0x8010, then 8 SCLK cycles;
--                               read data is valid on the SCLK FALLING edge.
-- The captured byte is latched and shown on the LEDs (active-low):
--   g1=bit7 g2=bit6 g3=bit5 g4=bit4 g5=bit3 g6=bit2 r1=bit1 r2=bit0, r6=heartbeat
-- Expect 0xD0 = 1101_0000  -> D1,D2,D4 green lit, rest dark.
--   all dark (0x00) or all lit (0xFF) => SPI/clock NOT working.
--
-- SPI: mode 0, MSB-first. Write bits sampled by the AD9912 on SCLK rising edge;
-- read bits driven by the AD9912, we sample on the SCLK falling edge.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_rb is
  port (
    dds_sclk, dds_sdio : out std_logic;
    dds_sdo            : in  std_logic;
    dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_rb is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';
  signal trig_cnt  : unsigned(18 downto 0) := (others => '0');
  signal go        : std_logic := '0';

  -- command sequence: 0=write 0x0000=01, 1=write 0x0010=D0, 2=read 0x0010
  type st_t is (IDLE, LOAD, TX_LO, TX_HI, RX_LO, RX_HI, CS_HI, GAP, FIN);
  signal st     : st_t := IDLE;
  signal cmd    : integer range 0 to 3 := 0;
  signal sh     : std_logic_vector(23 downto 0) := (others => '0'); -- left-justified tx
  signal txcnt  : integer range 0 to 24 := 0;
  signal rxcnt  : integer range 0 to 8  := 0;
  signal gapc   : integer range 0 to 7  := 0;
  signal cap    : std_logic_vector(7 downto 0) := (others => '0');
  signal result : std_logic_vector(7 downto 0) := (others => '0');
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

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
        st <= IDLE; dds_sclk <= '0'; dds_sdio <= '0'; dds_csb <= '1';
        cmd <= 0; cap <= (others => '0');
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1';
            if go = '1' then cmd <= 0; st <= LOAD; end if;

          when LOAD =>
            cap <= (others => '0');
            case cmd is
              when 0 => sh <= x"000001"; txcnt <= 24; rxcnt <= 0;  -- write 0x0000=0x01
              when 1 => sh <= x"0010D0"; txcnt <= 24; rxcnt <= 0;  -- write 0x0010=0xD0
              when others => sh <= x"801000"; txcnt <= 16; rxcnt <= 8; -- read 0x0010
            end case;
            dds_csb <= '0';
            st <= TX_LO;

          when TX_LO =>                       -- present MSB while clock low
            dds_sclk <= '0';
            dds_sdio <= sh(23);
            st <= TX_HI;

          when TX_HI =>                       -- rising edge: AD9912 samples our bit
            dds_sclk <= '1';
            if txcnt = 1 then
              if rxcnt > 0 then st <= RX_LO; else st <= CS_HI; end if;
            else
              sh <= sh(22 downto 0) & '0';
              txcnt <= txcnt - 1;
              st <= TX_LO;
            end if;

          when RX_LO =>                       -- falling edge: read data valid here
            dds_sclk <= '0';
            cap <= cap(6 downto 0) & dds_sdo;
            if rxcnt = 1 then st <= CS_HI; else rxcnt <= rxcnt - 1; st <= RX_HI; end if;

          when RX_HI =>                       -- rising edge: advance to next read bit
            dds_sclk <= '1';
            st <= RX_LO;

          when CS_HI =>
            dds_sclk <= '0'; dds_csb <= '1'; gapc <= 4; st <= GAP;

          when GAP =>
            if gapc = 0 then
              if cmd = 2 then st <= FIN; else cmd <= cmd + 1; st <= LOAD; end if;
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
