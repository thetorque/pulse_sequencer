-- sideband_spi.vhd -- Pico W sideband SPI1 slave (STUB: interface + safe idle).
-- The Pico (SPI1 master) sends standalone/CW setpoint commands {freq, amp} to the
-- ECP5 for bench / no-pulser operation; the ECP5 executes them via its own AD9912
-- SPI streamer (single-owner rule -- the Pico never drives the AD9912 directly).
-- 'attn' lets the ECP5 signal the Pico that status/ack is ready.
--
-- TODO: SPI slave shift (mode 0, MSB-first), command decode, setpoint regs out,
--       status/ack back on miso + attn.

library ieee;
use ieee.std_logic_1164.all;

entity sideband_spi is
  port (
    clk, rst : in  std_logic;
    sck      : in  std_logic;    -- from Pico GP10
    mosi     : in  std_logic;    -- Pico GP11 (command)
    cs       : in  std_logic;    -- Pico GP13 (active low)
    miso     : out std_logic;    -- to Pico GP12 (status)
    attn     : out std_logic     -- to Pico GP9 (attention/IRQ)
  );
end entity;

architecture stub of sideband_spi is
begin
  miso <= '0';
  attn <= '0';
end architecture;
