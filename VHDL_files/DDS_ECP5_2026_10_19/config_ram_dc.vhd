-- config_ram_dc.vhd -- AD9912 setpoint table, TRUE DUAL-CLOCK (inferred ECP5 EBR).
-- Same row layout as config_ram (DDS_BUS_CONTRACT.md §3). The write port runs in the
-- fast bus clock domain (bus_rx), the read port in the slower control domain (dds_ctl):
-- the EBR's unregistered-output clock-to-out (~5.8 ns at speed grade 6) plus the bank
-- mux does not fit the ~155 MHz fast clock, but fits ~77.5 MHz easily.
-- Read: 1-cycle registered (rclk). A row being written while it is read returns old or
-- new data; dds_ctl re-reads after every rows_written event, so this never matters.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity config_ram_dc is
  generic ( ADDR_W : integer := 13; DATA_W : integer := 88 );
  port (
    wclk  : in  std_logic;
    we    : in  std_logic;
    waddr : in  std_logic_vector(ADDR_W-1 downto 0);
    wdata : in  std_logic_vector(DATA_W-1 downto 0);
    rclk  : in  std_logic;
    raddr : in  std_logic_vector(ADDR_W-1 downto 0);
    rdata : out std_logic_vector(DATA_W-1 downto 0)
  );
end entity;

architecture rtl of config_ram_dc is
  type mem_t is array (0 to 2**ADDR_W-1) of std_logic_vector(DATA_W-1 downto 0);
  signal mem : mem_t := (others => (others => '0'));   -- driven only by the write process
begin
  process(wclk) begin
    if rising_edge(wclk) then
      if we = '1' then mem(to_integer(unsigned(waddr))) <= wdata; end if;
    end if;
  end process;

  process(rclk) begin
    if rising_edge(rclk) then
      rdata <= mem(to_integer(unsigned(raddr)));
    end if;
  end process;
end architecture;
