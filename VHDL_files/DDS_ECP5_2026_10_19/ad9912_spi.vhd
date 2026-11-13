-- ad9912_spi.vhd -- AD9912 SPI write engine (ECP5 = SPI master, 3-wire write only).
--
-- Two operations, one at a time (busy high while running):
--   start_row : one STREAMING write of POW + FTW from a config_ram row (80 bits):
--               instr 0x61AD (write, W1:W0=11 streaming, start 0x01AD) then, with the
--               address auto-DECREMENTING (MSB-first mode):
--                 0x01AD <- {00, POW[13:8]}   0x01AC <- POW[7:0]
--                 0x01AB .. 0x01A6 <- FTW[47:40] .. FTW[7:0]
--   start_reg : one single-byte register write (24 bits): instr {0,00,addr13} + data8.
-- NO IO_UPDATE here: FTW/POW land in the BUFFERED registers and the caller (dds_ctl)
-- strobes IO_UPDATE at the right moment (preload-then-strobe, DDS_BUS_CONTRACT §6).
--
-- Row layout (DDS_BUS_CONTRACT v0.2 §3): FTW48 = row(87:40); POW16 = row(39:24) as a
-- fraction of a turn -> the AD9912's 14-bit POW is the top 14 bits, row(39:26).
-- SPI mode 0, MSB first: SDIO changes while SCLK low, AD9912 samples on SCLK rising.
-- SCLK = clk / (2*DIV). AD9912 max SCLK = 50 MHz -> with the ~155 MHz (+-15 %) OSCG
-- use DIV >= 2 (DIV=2: ~39 MHz, DIV=3: ~26 MHz).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_spi is
  generic ( DIV : integer := 3 );                       -- clk cycles per SCLK half-period
  port (
    clk, rst  : in  std_logic;
    start_row : in  std_logic;                          -- pulse: stream POW+FTW of `row`
    row       : in  std_logic_vector(87 downto 0);
    start_reg : in  std_logic;                          -- pulse: write reg_addr <= reg_data
    reg_addr  : in  std_logic_vector(12 downto 0);
    reg_data  : in  std_logic_vector(7 downto 0);
    busy      : out std_logic;
    sclk      : out std_logic;
    sdio      : out std_logic;
    csb       : out std_logic                           -- active low
  );
end entity;

architecture rtl of ad9912_spi is
  constant ROW_INSTR : std_logic_vector(15 downto 0) := '0' & "11" & '0' & x"1AD";
  constant NMAX      : integer := 80;

  type st_t is (IDLE, BIT_LO, BIT_HI, CS_HI);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(NMAX-1 downto 0) := (others => '0');
  signal cnt  : integer range 0 to NMAX := 0;
  signal pre  : integer range 0 to DIV-1 := 0;
  signal busy_i : std_logic := '0';
begin
  busy <= busy_i or start_row or start_reg;             -- busy from the request cycle on

  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; sclk <= '0'; sdio <= '0'; csb <= '1'; busy_i <= '0'; pre <= 0;
      else
        case st is
          when IDLE =>
            sclk <= '0'; csb <= '1'; pre <= 0;
            if start_row = '1' then
              sh <= ROW_INSTR & "00" & row(39 downto 34) & row(33 downto 26) & row(87 downto 40);
              cnt <= 80; csb <= '0'; busy_i <= '1'; st <= BIT_LO;
            elsif start_reg = '1' then
              sh <= "000" & reg_addr & reg_data & (55 downto 0 => '0');
              cnt <= 24; csb <= '0'; busy_i <= '1'; st <= BIT_LO;
            else
              busy_i <= '0';
            end if;

          when BIT_LO =>                                -- SCLK low, present MSB
            sclk <= '0'; sdio <= sh(NMAX-1);
            if pre = DIV-1 then pre <= 0; st <= BIT_HI; else pre <= pre + 1; end if;

          when BIT_HI =>                                -- SCLK high: AD9912 samples
            sclk <= '1';
            if pre = DIV-1 then
              pre <= 0;
              if cnt = 1 then st <= CS_HI;
              else sh <= sh(NMAX-2 downto 0) & '0'; cnt <= cnt - 1; st <= BIT_LO; end if;
            else
              pre <= pre + 1;
            end if;

          when CS_HI =>
            sclk <= '0'; csb <= '1';
            if pre = DIV-1 then pre <= 0; busy_i <= '0'; st <= IDLE; else pre <= pre + 1; end if;
        end case;
      end if;
    end if;
  end process;
end architecture;
