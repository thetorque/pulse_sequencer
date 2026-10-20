-- tb_ad9912_spi.vhd -- self-checking testbench for ad9912_spi.
-- Models the AD9912 SPI slave: captures the 80-bit stream (instruction + POW + FTW)
-- on SCLK rising edges and checks the instruction word, POW bytes, FTW bytes, and
-- that IO_UPDATE pulsed.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_ad9912_spi is
end entity;

architecture sim of tb_ad9912_spi is
  signal clk       : std_logic := '0';
  signal rst       : std_logic := '1';
  signal start     : std_logic := '0';
  signal row       : std_logic_vector(87 downto 0) := (others => '0');
  signal busy      : std_logic;
  signal sclk      : std_logic;
  signal sdio      : std_logic;
  signal sdo       : std_logic := '0';
  signal csb       : std_logic;
  signal io_update : std_logic;

  constant TCLK : time := 20 ns;

  -- expected: instruction = write, streaming, start addr 0x01AD (POW MSB)
  constant START_ADDR : std_logic_vector(12 downto 0) := '0' & x"1AD";
  constant INSTR_EXP  : std_logic_vector(15 downto 0) := '0' & "11" & START_ADDR;  -- 0x61AD
  constant FTW_TEST   : std_logic_vector(47 downto 0) := x"123456789ABC";
  constant POW_TEST   : std_logic_vector(15 downto 0) := x"1234";                  -- phase[13:0]=0x1234
begin
  clk <= not clk after TCLK/2;

  dut : entity work.ad9912_spi
    port map ( clk => clk, rst => rst, start => start, row => row, busy => busy,
               sclk => sclk, sdio => sdio, sdo => sdo, csb => csb, io_update => io_update );

  stim : process
    variable cap : std_logic_vector(79 downto 0) := (others => '0');
    variable saw_update : boolean := false;
  begin
    row(87 downto 40) <= FTW_TEST;          -- FTW
    row(39 downto 24) <= POW_TEST;          -- POW (low 14 bits used)
    wait for 200 ns; rst <= '0'; wait for 100 ns;

    wait until rising_edge(clk); start <= '1';
    wait until rising_edge(clk); start <= '0';

    wait until csb = '0';
    for i in 0 to 79 loop
      wait until rising_edge(sclk);
      cap := cap(78 downto 0) & sdio;
    end loop;
    wait until csb = '1';

    report "instr=" & to_hstring(cap(79 downto 64))
         & " pow="  & to_hstring(cap(63 downto 48))
         & " ftw="  & to_hstring(cap(47 downto 0));

    assert cap(79 downto 64) = INSTR_EXP
      report "FAIL: instruction (got " & to_hstring(cap(79 downto 64)) & ")" severity error;
    assert cap(63 downto 56) = ("00" & POW_TEST(13 downto 8))     -- 0x01AD byte
      report "FAIL: POW MSB byte" severity error;
    assert cap(55 downto 48) = POW_TEST(7 downto 0)               -- 0x01AC byte
      report "FAIL: POW LSB byte" severity error;
    assert cap(47 downto 0) = FTW_TEST
      report "FAIL: FTW (got " & to_hstring(cap(47 downto 0)) & ")" severity error;

    for i in 0 to 20 loop
      wait for TCLK;
      if io_update = '1' then saw_update := true; end if;
    end loop;
    assert saw_update report "FAIL: IO_UPDATE never pulsed" severity error;

    if cap(79 downto 64) = INSTR_EXP
       and cap(63 downto 56) = ("00" & POW_TEST(13 downto 8))
       and cap(55 downto 48) = POW_TEST(7 downto 0)
       and cap(47 downto 0) = FTW_TEST and saw_update then
      report "PASS: ad9912_spi instruction + POW + FTW + IO_UPDATE correct" severity note;
    end if;
    std.env.stop;
  end process;
end architecture;
