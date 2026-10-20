-- tb_config_ram.vhd -- self-checking testbench for config_ram.
-- Writes a distinct pattern to every address, reads them all back, compares.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_config_ram is
end entity;

architecture sim of tb_config_ram is
  constant AW : integer := 4;    -- 16 rows (small for sim)
  constant DW : integer := 16;
  signal clk   : std_logic := '0';
  signal we    : std_logic := '0';
  signal waddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal raddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal wdata : std_logic_vector(DW-1 downto 0) := (others => '0');
  signal rdata : std_logic_vector(DW-1 downto 0);

  function pat(i : integer) return std_logic_vector is
  begin
    return std_logic_vector(to_unsigned((i*73 + 5) mod (2**DW), DW));
  end function;
begin
  clk <= not clk after 5 ns;

  dut : entity work.config_ram
    generic map ( ADDR_W => AW, DATA_W => DW )
    port map ( clk => clk, we => we, waddr => waddr, wdata => wdata,
               raddr => raddr, rdata => rdata );

  process
    variable errors : integer := 0;
  begin
    -- write every address
    for i in 0 to 2**AW-1 loop
      wait until rising_edge(clk);
      we <= '1'; waddr <= std_logic_vector(to_unsigned(i, AW)); wdata <= pat(i);
    end loop;
    wait until rising_edge(clk); we <= '0';

    -- read back + check (registered read -> allow latency)
    for i in 0 to 2**AW-1 loop
      raddr <= std_logic_vector(to_unsigned(i, AW));
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      if rdata /= pat(i) then
        report "FAIL addr " & integer'image(i) & " got=" & to_hstring(rdata)
             & " exp=" & to_hstring(pat(i)) severity error;
        errors := errors + 1;
      end if;
    end loop;

    if errors = 0 then report "PASS: config_ram write/read OK" severity note;
    else report "FAILED with " & integer'image(errors) & " errors" severity error; end if;
    std.env.stop;
  end process;
end architecture;
