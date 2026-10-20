-- ad9912_spi.vhd -- AD9912 4-wire SPI streamer (STUB: interface + safe idle).
-- On 'start', write the row's FTW/POW into the AD9912 registers over SPI, then
-- pulse IO_UPDATE. Target: double-buffered -- pre-stage the NEXT row during the
-- current dwell so 'start' (from backplane_stepnext) only needs to pulse IO_UPDATE
-- for a ~ns-deterministic switch.  RESET/PWRDWN are driven by the top, not here.
--
-- TODO: implement the SPI state machine (SPI mode per AD9912 datasheet: MSB-first,
--       instruction+address header then data bytes; CSB low per transfer).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_spi is
  port (
    clk, rst  : in  std_logic;
    start     : in  std_logic;                        -- pulse: stream this row
    row       : in  std_logic_vector(87 downto 0);    -- setpoint payload (see config_ram)
    busy      : out std_logic;
    -- AD9912 serial port
    sclk      : out std_logic;
    sdio      : out std_logic;                         -- MOSI
    sdo       : in  std_logic;                         -- MISO (readback)
    csb       : out std_logic;                         -- active low
    io_update : out std_logic
  );
end entity;

architecture stub of ad9912_spi is
begin
  -- safe idle: bus quiet, chip deselected, no update
  sclk      <= '0';
  sdio      <= '0';
  csb       <= '1';
  io_update <= '0';
  busy      <= '0';
end architecture;
