-- tb_bus_rx.vhd -- self-checking testbench for bus_rx (DDS_BUS_CONTRACT.md v0.2).
-- The TB plays the XEM7305 master: SPI mode 0, MSB first, CS-framed, at 1 / 25 /
-- 33 MHz SCK, against a slave clock of ~155 MHz (unrelated to SCK, like OSCG).
--   make sim TB=tb_bus_rx      -> ends with "tb_bus_rx: ALL TESTS PASSED"

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_bus_rx is end entity;

architecture sim of tb_bus_rx is
  constant ADDR_W : integer := 13;
  constant DATA_W : integer := 88;
  constant MYADDR : std_logic_vector(4 downto 0) := "00101";   -- board 5

  type row_arr  is array (natural range <>) of std_logic_vector(DATA_W-1 downto 0);

  signal clk : std_logic := '0';
  signal rst : std_logic := '1';
  signal sck, mosi : std_logic := '0';
  signal cs : std_logic := '1';

  signal we, rows_written, cmd_reset, cmd_step, reg_we, frame_err : std_logic;
  signal waddr : std_logic_vector(ADDR_W-1 downto 0);
  signal wdata : std_logic_vector(DATA_W-1 downto 0);
  signal reg_addr : std_logic_vector(15 downto 0);
  signal reg_data : std_logic_vector(7 downto 0);

  -- monitor: event counters + write log
  signal n_we, n_rw, n_rst, n_step, n_reg, n_err : integer := 0;
  signal log_a : row_arr(0 to 15);                         -- (address in low bits)
  signal log_d : row_arr(0 to 15);
  signal last_reg_addr : std_logic_vector(15 downto 0);
  signal last_reg_data : std_logic_vector(7 downto 0);

  function mkrow(k : integer) return std_logic_vector is
    variable r : std_logic_vector(DATA_W-1 downto 0);
  begin
    for b in 0 to DATA_W/8 - 1 loop                        -- distinct byte per position
      r(DATA_W-1-8*b downto DATA_W-8-8*b) := std_logic_vector(to_unsigned((k*37 + b*11 + 5) mod 256, 8));
    end loop;
    return r;
  end function;

  function hdr(addr : integer; ver : integer := 0) return std_logic_vector is
  begin
    return std_logic_vector(to_unsigned(ver, 3)) & std_logic_vector(to_unsigned(addr, 5));
  end function;
begin
  clk <= not clk after 3.225 ns;                           -- ~155 MHz

  dut : entity work.bus_rx
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W )
    port map ( clk => clk, rst => rst, bp_sck => sck, bp_mosi => mosi, bp_cs => cs,
               board_addr => MYADDR, we => we, waddr => waddr, wdata => wdata,
               rows_written => rows_written, cmd_reset => cmd_reset, cmd_step => cmd_step,
               reg_we => reg_we, reg_addr => reg_addr, reg_data => reg_data,
               frame_err => frame_err );

  monitor : process(clk) begin
    if rising_edge(clk) then
      if we = '1' then
        log_a(n_we mod 16) <= std_logic_vector(resize(unsigned(waddr), DATA_W));
        log_d(n_we mod 16) <= wdata;
        n_we <= n_we + 1;
      end if;
      if rows_written = '1' then n_rw   <= n_rw + 1;   end if;
      if cmd_reset    = '1' then n_rst  <= n_rst + 1;  end if;
      if cmd_step     = '1' then n_step <= n_step + 1; end if;
      if reg_we = '1' then
        n_reg <= n_reg + 1; last_reg_addr <= reg_addr; last_reg_data <= reg_data;
      end if;
      if frame_err = '1' then n_err <= n_err + 1; end if;
    end if;
  end process;

  stim : process
    variable half : time := 20 ns;                         -- 25 MHz
    variable fails : integer := 0;
    variable w0, rw0, r0, s0, g0, e0 : integer;

    -- send a frame (vector of whole bytes, sent MSB first); nbits >= 0 truncates
    procedure frame(b : std_logic_vector; nbits : integer := -1) is
      constant v : std_logic_vector(b'length-1 downto 0) := b;
      variable n : integer := b'length;
    begin
      if nbits >= 0 then n := nbits; end if;
      cs <= '0'; wait for half;
      for i in 0 to n-1 loop
        mosi <= v(b'length-1-i); wait for half;
        sck <= '1';              wait for half;
        sck <= '0';
      end loop;
      wait for half;
      cs <= '1';
      wait for 300 ns;                                     -- CS-high gap (>= 200 ns)
    end procedure;

    procedure snap is begin
      w0 := n_we; rw0 := n_rw; r0 := n_rst; s0 := n_step; g0 := n_reg; e0 := n_err;
    end procedure;

    procedure expect(name : string; dwe, drw, drst, dstep, dreg, derr : integer) is
    begin
      if n_we - w0 /= dwe or n_rw - rw0 /= drw or n_rst - r0 /= drst or
         n_step - s0 /= dstep or n_reg - g0 /= dreg or n_err - e0 /= derr then
        report name & ": FAIL  we=" & integer'image(n_we - w0) & " rows_written=" &
               integer'image(n_rw - rw0) & " reset=" & integer'image(n_rst - r0) &
               " step=" & integer'image(n_step - s0) & " reg=" & integer'image(n_reg - g0) &
               " err=" & integer'image(n_err - e0) severity error;
        fails := fails + 1;
      else
        report name & ": ok";
      end if;
    end procedure;

    procedure check_write(name : string; idx : integer; addr : integer; row : std_logic_vector) is
    begin
      if unsigned(log_a(idx mod 16)) /= addr or log_d(idx mod 16) /= row then
        report name & ": FAIL write #" & integer'image(idx) & " addr=" &
               integer'image(to_integer(unsigned(log_a(idx mod 16)))) &
               " (expected " & integer'image(addr) & ") or data mismatch" severity error;
        fails := fails + 1;
      end if;
    end procedure;

    variable start_w : integer;
  begin
    wait for 100 ns; rst <= '0'; wait for 200 ns;

    -- T1: WRITE_ROWS to this board, START=0x0010, 3 rows @ 25 MHz
    snap; start_w := n_we;
    frame(hdr(5) & x"01" & x"00" & x"10" & (mkrow(1)) & (mkrow(2)) & (mkrow(3)));
    expect("T1 write 3 rows (own addr, 25 MHz)", 3, 1, 0, 0, 0, 0);
    check_write("T1", start_w + 0, 16, mkrow(1));
    check_write("T1", start_w + 1, 17, mkrow(2));
    check_write("T1", start_w + 2, 18, mkrow(3));

    -- T2: same frame to another board -> nothing
    snap;
    frame(hdr(6) & x"01" & x"00" & x"10" & (mkrow(9)));
    expect("T2 other board ignored", 0, 0, 0, 0, 0, 0);

    -- T3: broadcast, START=8191 -> wraps to 0
    snap; start_w := n_we;
    frame(hdr(31) & x"01" & x"1F" & x"FF" & (mkrow(4)) & (mkrow(5)));
    expect("T3 broadcast + address wrap", 2, 1, 0, 0, 0, 0);
    check_write("T3", start_w + 0, 8191, mkrow(4));
    check_write("T3", start_w + 1, 0,    mkrow(5));

    -- T4: RESET (own), STEP (broadcast), STEP (other board)
    snap; frame(hdr(5)  & x"02"); expect("T4a RESET own", 0, 0, 1, 0, 0, 0);
    snap; frame(hdr(31) & x"03"); expect("T4b STEP broadcast", 0, 0, 0, 1, 0, 0);
    snap; frame(hdr(9)  & x"03"); expect("T4c STEP other board", 0, 0, 0, 0, 0, 0);

    -- T5: WRITE_REG 0x0010 = 0xD0
    snap; frame(hdr(5) & x"04" & x"00" & x"10" & x"D0");
    expect("T5 WRITE_REG", 0, 0, 0, 0, 1, 0);
    if last_reg_addr /= x"0010" or last_reg_data /= x"D0" then
      report "T5: FAIL reg value" severity error; fails := fails + 1;
    end if;

    -- T6: truncated WRITE_ROWS: 1 full row + 5 bytes + 3 bits -> 1 write, error
    snap; start_w := n_we;
    frame(hdr(5) & x"01" & x"00" & x"20" & (mkrow(6)) & (mkrow(7)),
          8 * (4 + 11 + 5) + 3);
    expect("T6 truncated row dropped + flagged", 1, 1, 0, 0, 0, 1);
    check_write("T6", start_w, 32, mkrow(6));

    -- T7: unknown CMD (own) -> error ; non-zero version -> ignored silently
    snap; frame(hdr(5) & x"7E" & x"12"); expect("T7a unknown CMD", 0, 0, 0, 0, 0, 1);
    snap; frame(hdr(5, 1) & x"02");      expect("T7b version!=0 ignored", 0, 0, 0, 0, 0, 0);

    -- T8: RESET with a payload byte -> error, not executed ; short WRITE_REG -> error
    snap; frame(hdr(5) & x"02" & x"00");         expect("T8a RESET + extra byte", 0, 0, 0, 0, 0, 1);
    snap; frame(hdr(5) & x"04" & x"00" & x"10"); expect("T8b WRITE_REG too short", 0, 0, 0, 0, 0, 1);

    -- T9: NOP with junk payload -> nothing
    snap; frame(hdr(5) & x"00" & x"AA" & x"55"); expect("T9 NOP", 0, 0, 0, 0, 0, 0);

    -- T10: 33 MHz SCK
    half := 15 ns;
    snap; start_w := n_we;
    frame(hdr(5) & x"01" & x"01" & x"00" & (mkrow(8)) & (mkrow(9)));
    expect("T10 write 2 rows @ 33 MHz", 2, 1, 0, 0, 0, 0);
    check_write("T10", start_w + 0, 256, mkrow(8));
    check_write("T10", start_w + 1, 257, mkrow(9));
    snap; frame(hdr(5) & x"03"); expect("T10b STEP @ 33 MHz", 0, 0, 0, 1, 0, 0);

    -- T11: 1 MHz SCK
    half := 500 ns;
    snap; start_w := n_we;
    frame(hdr(31) & x"01" & x"00" & x"05" & (mkrow(10)));
    expect("T11 write 1 row @ 1 MHz", 1, 1, 0, 0, 0, 0);
    check_write("T11", start_w, 5, mkrow(10));

    if fails = 0 then report "tb_bus_rx: ALL TESTS PASSED";
    else report "tb_bus_rx: " & integer'image(fails) & " FAILURE(S)" severity error; end if;
    std.env.stop;
  end process;
end architecture;
