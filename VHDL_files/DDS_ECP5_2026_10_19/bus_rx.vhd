-- bus_rx.vhd -- pulser backplane DDS-bus receiver (STUB: interface + safe idle).
-- New serial protocol (see [[dds-slave-board]]): the pulser is SPI master, pushing
-- frames [ADDR(4-5b) | CMD(4b) | payload...] on bp_sck/bp_mosi, delimited by bp_cs.
-- Every board shifts the frame; only the board whose strapped board_addr matches the
-- frame ADDR (or the broadcast addr) consumes the payload and writes it into config_ram.
-- step_next / ram_reset are BROADCAST wires handled in the top (not framed here).
--
-- TODO: implement frame shift-in, ADDR compare vs board_addr, payload -> RAM writes,
--       and MISO readback (tri-stated unless addressed). Cross bp_* into clk domain.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bus_rx is
  generic ( ADDR_W : integer := 10; DATA_W : integer := 88 );
  port (
    clk, rst   : in  std_logic;
    -- backplane bus (single-ended, after the DS90LV048A LVDS receiver)
    bp_sck     : in  std_logic;
    bp_mosi    : in  std_logic;
    bp_cs      : in  std_logic;
    board_addr : in  std_logic_vector(4 downto 0);
    -- write port into config_ram
    we    : out std_logic;
    waddr : out std_logic_vector(ADDR_W-1 downto 0);
    wdata : out std_logic_vector(DATA_W-1 downto 0)
  );
end entity;

architecture stub of bus_rx is
begin
  we    <= '0';
  waddr <= (others => '0');
  wdata <= (others => '0');
end architecture;
