-- ad9912_spi.vhd -- AD9912 SPI engine (ECP5 = SPI master, 3-wire: SDIO is bidirectional).
--
-- Three operations, one at a time (busy high while running):
--   start_row : one STREAMING write of POW + FTW from a config_ram row (80 bits):
--               instr 0x61AD (write, W1:W0=11 streaming, start 0x01AD) then, with the
--               address auto-DECREMENTING (MSB-first mode):
--                 0x01AD <- {00, POW[13:8]}   0x01AC <- POW[7:0]
--                 0x01AB .. 0x01A6 <- FTW[47:40] .. FTW[7:0]
--   start_reg : one single-byte register write (24 bits): instr {0,00,addr13} + data8.
--   start_rd  : one single-byte register READ (24 clocks): instr {1,00,addr13} driven on
--               SDIO, then SDIO is released (sdio_oe = 0) and the AD9912 shifts the byte
--               out on SDIO (3-wire default mode -- the board's SDO pin 62 is open).
--               rd_data is valid once busy drops. Reads run at the slow RD_DIV (only used
--               for the start-up part-ID check, so speed doesn't matter and the AD9912's
--               output-valid time never limits). Proven on hardware by ad9912_idcheck.
-- NO IO_UPDATE here: FTW/POW land in the BUFFERED registers and the caller (dds_ctl)
-- strobes IO_UPDATE at the right moment (preload-then-strobe, DDS_BUS_CONTRACT §6).
--
-- Row layout (DDS_BUS_CONTRACT §3): FTW48 = row(87:40); POW16 = row(39:24) as a
-- fraction of a turn -> the AD9912's 14-bit POW is the top 14 bits, row(39:26).
-- SPI mode 0, MSB first: SDIO changes while SCLK low, AD9912 samples on SCLK rising;
-- read data changes after SCLK falling and is sampled late in the SCLK-high phase.
-- SCLK = clk / (2*DIV) for writes, clk / (2*RD_DIV) for reads. AD9912 max SCLK =
-- 50 MHz -> with clk_s ~77.5 MHz (+-15 %) DIV = 1 gives ~39 MHz.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_spi is
  generic ( DIV : integer := 3;                          -- clk per SCLK half-period (writes)
            RD_DIV : integer := 8 );                     -- clk per SCLK half-period (reads)
  port (
    clk, rst  : in  std_logic;
    start_row : in  std_logic;                          -- pulse: stream POW+FTW of `row`
    row       : in  std_logic_vector(87 downto 0);
    start_reg : in  std_logic;                          -- pulse: write reg_addr <= reg_data
    reg_addr  : in  std_logic_vector(12 downto 0);
    reg_data  : in  std_logic_vector(7 downto 0);
    start_rd  : in  std_logic;                          -- pulse: read rd_addr
    rd_addr   : in  std_logic_vector(12 downto 0);
    rd_data   : out std_logic_vector(7 downto 0);       -- valid when busy drops after a read
    busy      : out std_logic;
    sclk      : out std_logic;
    sdio_o    : out std_logic;
    sdio_oe   : out std_logic;                          -- 1: FPGA drives SDIO
    sdio_i    : in  std_logic;
    csb       : out std_logic                           -- active low
  );
end entity;

architecture rtl of ad9912_spi is
  constant ROW_INSTR : std_logic_vector(15 downto 0) := '0' & "11" & '0' & x"1AD";
  constant NMAX      : integer := 80;
  constant PMAX      : integer := maximum(DIV, RD_DIV);

  type st_t is (IDLE, BIT_LO, BIT_HI, CS_HI);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(NMAX-1 downto 0) := (others => '0');
  signal cnt  : integer range 0 to NMAX := 0;
  signal pre  : integer range 0 to PMAX-1 := 0;
  signal hd   : integer range 1 to PMAX := DIV;          -- half-period of this operation
  signal rd   : std_logic := '0';                        -- this operation is a read
  signal rxb  : std_logic_vector(7 downto 0) := (others => '0');
  signal si1, si2 : std_logic := '0';                    -- SDIO input synchroniser
  signal busy_i : std_logic := '0';
begin
  busy <= busy_i or start_row or start_reg or start_rd; -- busy from the request cycle on

  process(clk) begin
    if rising_edge(clk) then
      si1 <= sdio_i; si2 <= si1;
      if rst = '1' then
        st <= IDLE; sclk <= '0'; sdio_o <= '0'; sdio_oe <= '1'; csb <= '1';
        busy_i <= '0'; pre <= 0; rd <= '0';
      else
        case st is
          when IDLE =>
            sclk <= '0'; csb <= '1'; sdio_oe <= '1'; pre <= 0;
            if start_row = '1' then
              sh <= ROW_INSTR & "00" & row(39 downto 34) & row(33 downto 26) & row(87 downto 40);
              cnt <= 80; csb <= '0'; busy_i <= '1'; rd <= '0'; hd <= DIV; st <= BIT_LO;
            elsif start_reg = '1' then
              sh <= "000" & reg_addr & reg_data & (55 downto 0 => '0');
              cnt <= 24; csb <= '0'; busy_i <= '1'; rd <= '0'; hd <= DIV; st <= BIT_LO;
            elsif start_rd = '1' then
              sh <= "100" & rd_addr & (63 downto 0 => '0');
              cnt <= 24; csb <= '0'; busy_i <= '1'; rd <= '1'; hd <= RD_DIV; st <= BIT_LO;
            else
              busy_i <= '0';
            end if;

          when BIT_LO =>                                -- SCLK low, present MSB
            sclk <= '0'; sdio_o <= sh(NMAX-1);
            if rd = '1' and cnt <= 8 then sdio_oe <= '0'; else sdio_oe <= '1'; end if;
            if pre = hd-1 then pre <= 0; st <= BIT_HI; else pre <= pre + 1; end if;

          when BIT_HI =>                                -- SCLK high: AD9912 samples
            sclk <= '1';
            -- read: let go of SDIO one clk after the last instruction bit's rising edge
            -- (hold time met), before the AD9912 starts driving on the next falling edge
            if rd = '1' and cnt = 9 and pre = 1 then sdio_oe <= '0'; end if;
            if pre = hd-1 then
              pre <= 0;
              if rd = '1' and cnt <= 8 then rxb <= rxb(6 downto 0) & si2; end if;
              if cnt = 1 then st <= CS_HI;
              else sh <= sh(NMAX-2 downto 0) & '0'; cnt <= cnt - 1; st <= BIT_LO; end if;
            else
              pre <= pre + 1;
            end if;

          when CS_HI =>
            sclk <= '0'; csb <= '1'; sdio_oe <= '1';
            if rd = '1' then rd_data <= rxb; end if;
            if pre = hd-1 then pre <= 0; busy_i <= '0'; st <= IDLE; else pre <= pre + 1; end if;
        end case;
      end if;
    end if;
  end process;
end architecture;
