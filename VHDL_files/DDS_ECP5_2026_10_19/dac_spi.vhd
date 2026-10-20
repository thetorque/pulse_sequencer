-- dac_spi.vhd -- MCP4821 amplitude-DAC SPI master.
-- On 'start', writes a 12-bit code into the MCP4821 then pulses LDAC so VOUT
-- updates.  MCP4821 16-bit frame (MSB first), config nibble = "0011":
--   bit15 A/B=0 | bit14 BUF=0 | bit13 GA=1 (1x gain, FS=2.048 V) | bit12 SHDN=1 (active)
--   bits11..0 = data.   VOUT = 2.048 * code/4096.
-- SPI mode 0: data presented while SCK low, latched on SCK rising edge.
-- VOUT updates on the LDAC falling edge (pulsed after CS deassert).
-- SCK ~= clk/2 (~1.2 MHz off the 2.4 MHz OSCG) -- well under MCP4821's 20 MHz.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dac_spi is
  port (
    clk, rst : in  std_logic;
    start    : in  std_logic;
    code     : in  std_logic_vector(11 downto 0);
    busy     : out std_logic;
    sck      : out std_logic;
    sdi      : out std_logic;
    cs       : out std_logic;     -- active low
    ldac     : out std_logic      -- active low strobe
  );
end entity;

architecture rtl of dac_spi is
  type st_t is (IDLE, BIT_LO, BIT_HI, DESEL, LAT_LO, LAT_HI);
  signal st     : st_t := IDLE;
  signal sh     : std_logic_vector(15 downto 0) := (others => '0');
  signal cnt    : integer range 0 to 15 := 0;
  signal latcnt : integer range 0 to 7 := 0;
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; sck <= '0'; sdi <= '0'; cs <= '1'; ldac <= '1'; busy <= '0';
      else
        case st is
          when IDLE =>
            sck <= '0'; cs <= '1'; ldac <= '1'; busy <= '0';
            if start = '1' then
              sh   <= "0011" & code;     -- config nibble + 12-bit data
              cnt  <= 15;
              cs   <= '0';
              busy <= '1';
              st   <= BIT_LO;
            end if;

          when BIT_LO =>                 -- present MSB while clock low
            sck <= '0';
            sdi <= sh(15);
            st  <= BIT_HI;

          when BIT_HI =>                 -- rising edge -> MCP4821 samples
            sck <= '1';
            if cnt = 0 then
              st <= DESEL;
            else
              sh  <= sh(14 downto 0) & '0';
              cnt <= cnt - 1;
              st  <= BIT_LO;
            end if;

          when DESEL =>                  -- deassert CS, then strobe LDAC
            sck <= '0'; cs <= '1'; latcnt <= 3; st <= LAT_LO;

          when LAT_LO =>                 -- LDAC low -> VOUT updates on this falling edge
            ldac <= '0';
            if latcnt = 0 then st <= LAT_HI; else latcnt <= latcnt - 1; end if;

          when LAT_HI =>
            ldac <= '1'; busy <= '0'; st <= IDLE;
        end case;
      end if;
    end if;
  end process;
end architecture;
