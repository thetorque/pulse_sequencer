-- dac_spi.vhd -- MCP4821 amplitude-DAC SPI master (STUB: interface + safe idle).
-- Writes a 12-bit code into the MCP4821 (16-bit frame: config nibble + 12-bit data),
-- then pulses LDAC to update VOUT -> ADL5330 VGA gain control (VDBS).
-- Pre-stage during dwell, strobe LDAC on 'start' (amplitude analog of IO_UPDATE).
--
-- TODO: implement the 16-bit SPI write + LDAC strobe (MCP4821 is write-only, no MISO).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dac_spi is
  port (
    clk, rst : in  std_logic;
    start    : in  std_logic;
    code     : in  std_logic_vector(11 downto 0);
    busy     : out std_logic;
    -- MCP4821 serial port
    sck      : out std_logic;
    sdi      : out std_logic;
    cs       : out std_logic;     -- active low
    ldac     : out std_logic      -- active low strobe
  );
end entity;

architecture stub of dac_spi is
begin
  sck  <= '0';
  sdi  <= '0';
  cs   <= '1';
  ldac <= '1';
  busy <= '0';
end architecture;
