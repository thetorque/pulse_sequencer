-- tb_ad9912_spi.vhd -- self-checking testbench for ad9912_spi.
-- Models the AD9912 SPI slave: captures each CSB-framed stream on SCLK rising edges.
--   1. start_row: 80-bit stream = instr 0x61AD + {00,POW[13:8]} + POW[7:0] + FTW48, with
--      POW = top 14 bits of the row's 16-bit turn-fraction field (DDS_BUS_CONTRACT §3).
--   2. start_reg: 24-bit stream = instr {0,00,addr13} + data8.
-- (IO_UPDATE is no longer driven by ad9912_spi -- dds_ctl strobes it.)
--   make sim TB=tb_ad9912_spi

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_ad9912_spi is
end entity;

architecture sim of tb_ad9912_spi is
  signal clk       : std_logic := '0';
  signal rst       : std_logic := '1';
  signal start_row : std_logic := '0';
  signal start_reg : std_logic := '0';
  signal row       : std_logic_vector(87 downto 0) := (others => '0');
  signal reg_addr  : std_logic_vector(12 downto 0) := '0' & x"40B";
  signal reg_data  : std_logic_vector(7 downto 0)  := x"A5";
  signal busy      : std_logic;
  signal sclk      : std_logic;
  signal sdio      : std_logic;
  signal csb       : std_logic;

  constant TCLK : time := 13 ns;                                         -- ~77 MHz

  constant INSTR_ROW : std_logic_vector(15 downto 0) := x"61AD";        -- write, streaming, 0x01AD
  constant FTW_TEST  : std_logic_vector(47 downto 0) := x"123456789ABC";
  constant POW_TEST  : std_logic_vector(15 downto 0) := x"8004";        -- 180.02 deg
  constant POW14     : std_logic_vector(13 downto 0) := POW_TEST(15 downto 2);
begin
  clk <= not clk after TCLK/2;

  dut : entity work.ad9912_spi
    generic map ( DIV => 1 )
    port map ( clk => clk, rst => rst, start_row => start_row, row => row,
               start_reg => start_reg, reg_addr => reg_addr, reg_data => reg_data,
               busy => busy, sclk => sclk, sdio => sdio, csb => csb );

  stim : process
    variable cap : std_logic_vector(79 downto 0) := (others => '0');
    variable n   : integer;
    variable fails : integer := 0;
  begin
    row(87 downto 40) <= FTW_TEST;
    row(39 downto 24) <= POW_TEST;
    wait for 200 ns; rst <= '0'; wait for 100 ns;

    -- 1. row stream
    wait until rising_edge(clk); start_row <= '1';
    wait until rising_edge(clk); start_row <= '0';
    wait until csb = '0'; n := 0;
    loop
      wait until rising_edge(sclk) or rising_edge(csb);
      exit when csb = '1';
      cap := cap(78 downto 0) & sdio; n := n + 1;
    end loop;
    report "row: bits=" & integer'image(n) & " instr=" & to_hstring(cap(79 downto 64)) &
           " pow=" & to_hstring(cap(63 downto 48)) & " ftw=" & to_hstring(cap(47 downto 0));
    if n /= 80 or cap(79 downto 64) /= INSTR_ROW or
       cap(63 downto 48) /= ("00" & POW14) or cap(47 downto 0) /= FTW_TEST then
      report "FAIL: row stream" severity error; fails := fails + 1;
    end if;
    wait until busy = '0';

    -- 2. single register write
    wait until rising_edge(clk); start_reg <= '1';
    wait until rising_edge(clk); start_reg <= '0';
    wait until csb = '0'; n := 0;
    loop
      wait until rising_edge(sclk) or rising_edge(csb);
      exit when csb = '1';
      cap := cap(78 downto 0) & sdio; n := n + 1;
    end loop;
    report "reg: bits=" & integer'image(n) & " instr=" & to_hstring(cap(23 downto 8)) &
           " data=" & to_hstring(cap(7 downto 0));
    if n /= 24 or cap(23 downto 8) /= x"040B" or cap(7 downto 0) /= x"A5" then
      report "FAIL: register write" severity error; fails := fails + 1;
    end if;

    if fails = 0 then report "PASS: ad9912_spi row stream + register write correct";
    else report "tb_ad9912_spi: FAILED" severity error; end if;
    std.env.stop;
  end process;
end architecture;
