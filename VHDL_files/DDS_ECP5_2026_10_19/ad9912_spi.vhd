-- ad9912_spi.vhd -- AD9912 4-wire SPI streamer: writes POW + FTW, pulses IO_UPDATE.
--
-- Confirmed from the AD9912 data sheet (Rev. G):
--   * FTW  : 48-bit, registers 0x01A6 (LSB) .. 0x01AB (MSB).
--   * POW  : 14-bit phase, registers 0x01AC (LSB) .. 0x01AD (MSB).
--   * Instruction word (16-bit, Table 10): bit15 = R/W (0=write), bits14:13 = W1:W0
--     transfer length (11 = streaming), bits12:0 = 13-bit start address.
--   * Default MSB-first; in streaming/MSB-first the internal address DECREMENTS,
--     so a write starting at the MSB address proceeds down toward the LSB.
--   * Write data is sampled on the SCLK RISING edge (SPI mode 0).
--   * CSB raised at the end terminates the stream.
--   * FTW and POW are buffered ("M") registers -> a single IO_UPDATE rising edge
--     (or reg 0x0005 bit0) transfers both to the active core.
--
-- One streaming write from 0x01AD covers POW then FTW (8 bytes), decrementing:
--   0x01AD<-{00,POW[13:8]} 0x01AC<-POW[7:0] 0x01AB<-FTW[47:40] .. 0x01A6<-FTW[7:0]
--
-- Row layout (see config_ram):  FTW = row(87:40) ; POW[13:0] = row(37:24).
-- TODO: split "pre-stage write" from the "IO_UPDATE strobe" for double-buffered,
--       ns-deterministic step switching (pre-stage during dwell, strobe on step).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_spi is
  port (
    clk, rst  : in  std_logic;
    start     : in  std_logic;                        -- pulse: stream this row
    row       : in  std_logic_vector(87 downto 0);
    busy      : out std_logic;
    sclk      : out std_logic;
    sdio      : out std_logic;                         -- MOSI
    sdo       : in  std_logic;                         -- MISO (unused in write path)
    csb       : out std_logic;                         -- active low
    io_update : out std_logic
  );
end entity;

architecture rtl of ad9912_spi is
  constant START_ADDR : std_logic_vector(12 downto 0) := '0' & x"1AD";   -- POW MSB
  constant INSTR      : std_logic_vector(15 downto 0) := '0' & "11" & START_ADDR;
  constant NBITS      : integer := 80;                 -- 16 instr + 8 + 8 (POW) + 48 (FTW)

  type st_t is (IDLE, BIT_LO, BIT_HI, CS_HI, UPD_HI, UPD_LO);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(NBITS-1 downto 0) := (others => '0');
  signal cnt  : integer range 0 to NBITS := 0;
  signal updc : integer range 0 to 7 := 0;
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; sclk <= '0'; sdio <= '0'; csb <= '1'; io_update <= '0'; busy <= '0';
      else
        case st is
          when IDLE =>
            sclk <= '0'; csb <= '1'; io_update <= '0'; busy <= '0';
            if start = '1' then
              -- instruction + POW(hi,lo) + FTW(48), MSB first
              sh   <= INSTR
                    & "00" & row(37 downto 32)   -- 0x01AD: {00, POW[13:8]}
                    & row(31 downto 24)          -- 0x01AC: POW[7:0]
                    & row(87 downto 40);         -- 0x01AB..0x01A6: FTW[47:0]
              cnt  <= NBITS;
              csb  <= '0';
              busy <= '1';
              st   <= BIT_LO;
            end if;

          when BIT_LO =>                        -- present MSB while clock low
            sclk <= '0';
            sdio <= sh(NBITS-1);
            st   <= BIT_HI;

          when BIT_HI =>                        -- rising edge -> AD9912 samples
            sclk <= '1';
            if cnt = 1 then
              st <= CS_HI;
            else
              sh  <= sh(NBITS-2 downto 0) & '0';
              cnt <= cnt - 1;
              st  <= BIT_LO;
            end if;

          when CS_HI =>                         -- end transfer, then strobe IO_UPDATE
            sclk <= '0'; csb <= '1'; updc <= 3; st <= UPD_HI;

          when UPD_HI =>
            io_update <= '1';                   -- rising edge transfers buffered POW/FTW
            if updc = 0 then st <= UPD_LO; else updc <= updc - 1; end if;

          when UPD_LO =>
            io_update <= '0'; busy <= '0'; st <= IDLE;
        end case;
      end if;
    end if;
  end process;
end architecture;
