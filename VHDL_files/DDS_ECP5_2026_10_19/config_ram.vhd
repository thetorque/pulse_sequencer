-- config_ram.vhd -- AD9912 setpoint table (inferred ECP5 EBR, dual-port).
-- One row = one sequence step's payload. Field layout (DATA_W=88, 11 bytes):
--   [87:40] FTW   48-bit frequency tuning word (AD9912)
--   [39:24] POW   16-bit phase offset word      (AD9912; confirm 14 vs 16)
--   [23: 8] AMP   16-bit amplitude code          (external MCP4821 DAC)
--   [ 7: 0] CTRL   8-bit flags (end/valid/output-select)  -- TODO define
-- Write port: filled by bus_rx from the pulser.  Read port: ad9912_spi streamer.
-- Scale ADDR_W to 13 (8192 rows) for the full table; 10 here keeps skeleton builds light.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity config_ram is
  generic ( ADDR_W : integer := 10; DATA_W : integer := 88 );
  port (
    clk   : in  std_logic;
    we    : in  std_logic;
    waddr : in  std_logic_vector(ADDR_W-1 downto 0);
    wdata : in  std_logic_vector(DATA_W-1 downto 0);
    raddr : in  std_logic_vector(ADDR_W-1 downto 0);
    rdata : out std_logic_vector(DATA_W-1 downto 0)
  );
end entity;

architecture rtl of config_ram is
  type mem_t is array (0 to 2**ADDR_W-1) of std_logic_vector(DATA_W-1 downto 0);
  signal mem : mem_t := (others => (others => '0'));
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if we = '1' then
        mem(to_integer(unsigned(waddr))) <= wdata;
      end if;
      rdata <= mem(to_integer(unsigned(raddr)));   -- 1-cycle registered read
    end if;
  end process;
end architecture;
