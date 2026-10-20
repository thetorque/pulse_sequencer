-- tb_sideband_spi.vhd -- self-checking testbench for sideband_spi.
-- Drives an SPI master (mode 0, MSB-first) sending 4 bytes; checks the slave
-- returns SIGNATURE(0xA5) then an echo of the previous byte.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_sideband_spi is
end entity;

architecture sim of tb_sideband_spi is
  signal clk      : std_logic := '0';
  signal rst      : std_logic := '1';
  signal sck      : std_logic := '0';
  signal mosi     : std_logic := '0';
  signal cs       : std_logic := '1';
  signal miso     : std_logic;
  signal attn     : std_logic;
  signal rx_valid : std_logic;
  signal rx_byte  : std_logic_vector(7 downto 0);

  constant TCLK  : time := 20 ns;    -- 50 MHz fabric (oversamples the slow SCK)
  constant THALF : time := 500 ns;   -- SCK half-period (1 MHz) >> clk
begin
  clk <= not clk after TCLK/2;

  dut : entity work.sideband_spi
    port map ( clk => clk, rst => rst, sck => sck, mosi => mosi, cs => cs,
               miso => miso, attn => attn, rx_byte => rx_byte, rx_valid => rx_valid );

  stim : process
    variable errors : integer := 0;

    procedure xfer(tx : in std_logic_vector(7 downto 0);
                   rxb : out std_logic_vector(7 downto 0)) is
    begin
      for i in 7 downto 0 loop
        mosi <= tx(i);
        wait for THALF;
        sck <= '1';
        rxb(i) := miso;       -- master samples MISO on the rising edge
        wait for THALF;
        sck <= '0';
      end loop;
    end procedure;

    variable r0, r1, r2, r3 : std_logic_vector(7 downto 0);

    procedure check(name : string; got, exp : std_logic_vector(7 downto 0)) is
    begin
      if got /= exp then
        report "FAIL " & name & " got=" & to_hstring(got) & " exp=" & to_hstring(exp)
          severity error;
      end if;
    end procedure;
  begin
    wait for 1 us; rst <= '0'; wait for 1 us;

    cs <= '0'; wait for 2 us;           -- start frame
    xfer(x"3C", r0);
    xfer(x"81", r1);
    xfer(x"55", r2);
    xfer(x"F0", r3);
    wait for 1 us;
    cs <= '1'; wait for 2 us;           -- end frame

    report "resp = " & to_hstring(r0) & " " & to_hstring(r1) & " "
         & to_hstring(r2) & " " & to_hstring(r3);
    check("resp0(SIG)", r0, x"A5");
    check("resp1(echo 3C)", r1, x"3C");
    check("resp2(echo 81)", r2, x"81");
    check("resp3(echo 55)", r3, x"55");

    report "sideband_spi testbench DONE" severity note;
    std.env.stop;
  end process;
end architecture;
