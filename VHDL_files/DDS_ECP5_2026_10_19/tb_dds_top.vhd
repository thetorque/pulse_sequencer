-- tb_dds_top.vhd -- full DDS-board simulation (DDS_BUS_CONTRACT.md v0.2).
-- The TB is the XEM7305 master (backplane frames + STEPNEXT/RAMRESET pulses) AND the
-- board's chips: an AD9912 register model (buffered FTW/POW, made active by an
-- IO_UPDATE rising edge; single-byte register writes) and an MCP4821 model (input
-- register, output updated by LDAC falling). It checks what is ACTUALLY live after
-- each step / reset / register write, and the STEPNEXT -> IO_UPDATE latency.
--   make sim TB=tb_dds_top     -> ends with "tb_dds_top: ALL TESTS PASSED"

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_dds_top is end entity;

architecture sim of tb_dds_top is
  signal dds_sclk, dds_sdio, dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : std_logic;
  signal vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn, rf_main_sw : std_logic;
  signal sck, mosi : std_logic := '0';
  signal cs, stepnext, ramreset : std_logic := '1';   -- undriven lines idle HIGH (fail-safe)
  signal leds : std_logic_vector(11 downto 0);
  signal pico_rx, pico_attn : std_logic;
  signal psram : std_logic_vector(5 downto 0);
  signal auxo  : std_logic_vector(6 downto 0);
  constant ADDR : std_logic_vector(4 downto 0) := "00101";

  -- AD9912 model
  type regmap_t is array (0 to 16#5FF#) of std_logic_vector(7 downto 0);
  signal ad_buf   : regmap_t := (others => (others => '0'));
  signal act_ftw  : std_logic_vector(47 downto 0) := (others => '0');
  signal act_pow  : std_logic_vector(13 downto 0) := (others => '0');
  signal n_upd, n_regw, n_roww : integer := 0;
  signal t_upd    : time := 0 ns;
  signal last_reg : std_logic_vector(23 downto 0);
  -- MCP4821 model
  signal dac_in, dac_out : std_logic_vector(15 downto 0) := (others => '0');

  function mkrow(ftw : std_logic_vector(47 downto 0); pow : std_logic_vector(15 downto 0);
                 vga : std_logic_vector(11 downto 0); rf : std_logic) return std_logic_vector is
  begin
    return ftw & pow & vga & "0000" & "0000000" & rf;
  end function;

  constant R0 : std_logic_vector(87 downto 0) := mkrow(x"0CCCCCCCCCCD", x"0000", x"B40", '1');
  constant R1 : std_logic_vector(87 downto 0) := mkrow(x"4CCCCCCCCCCD", x"4000", x"A11", '1');
  constant R2 : std_logic_vector(87 downto 0) := mkrow(x"1F9ADD373963", x"8004", x"C6F", '0');
  constant R3 : std_logic_vector(87 downto 0) := mkrow(x"028F5C28F5C3", x"FFFC", x"123", '1');
  constant R9 : std_logic_vector(87 downto 0) := mkrow(x"111111111111", x"2222", x"333", '1');
begin
  dut : entity work.dds_top port map (
    dds_sclk => dds_sclk, dds_sdio => dds_sdio, dds_csb => dds_csb,
    dds_ioupdate => dds_ioupdate, dds_reset => dds_reset, dds_pwrdwn => dds_pwrdwn,
    dds_sdo => '0',
    vga_sck => vga_sck, vga_sci => vga_sci, vga_cs => vga_cs, vga_ldac => vga_ldac,
    vga_shdn => vga_shdn, rf_main_sw => rf_main_sw,
    backplane_sck => sck, backplane_mosi => mosi, backplane_cs => cs,
    backplane_stepnext => stepnext, backplane_ramreset => ramreset,
    backplane_aux1 => '1', backplane_aux2 => '1', backplane_aux3 => '1',
    pico_w_sck_aux => '0', pico_w_tx_aux => '0', pico_w_cs_aux => '1',
    pico_w_rx_aux => pico_rx, pico_w_attn => pico_attn,
    add0 => ADDR(0), add1 => ADDR(1), add2 => ADDR(2), add3 => ADDR(3), add4 => ADDR(4),
    psram_sclk => psram(0), psram_si => psram(1), psram_so => psram(2),
    psram_sio2 => psram(3), psram_sio3 => psram(4), psram_cen => psram(5),
    aux0 => auxo(0), aux1 => auxo(1), aux2 => auxo(2), aux3 => auxo(3),
    aux4 => auxo(4), aux5 => auxo(5), aux6 => auxo(6),
    led_g1 => leds(0), led_g2 => leds(1), led_g3 => leds(2), led_g4 => leds(3),
    led_g5 => leds(4), led_g6 => leds(5), led_r1 => leds(6), led_r2 => leds(7),
    led_r3 => leds(8), led_r4 => leds(9), led_r5 => leds(10), led_r6 => leds(11) );

  -- ---------------- AD9912 model ----------------
  ad_model : process
    variable sh : std_logic_vector(255 downto 0);
    variable n  : integer;
    variable instr : std_logic_vector(15 downto 0);
    variable a  : integer;
    variable nbytes : integer;
  begin
    wait until falling_edge(dds_csb);
    n := 0;
    loop
      wait until rising_edge(dds_sclk) or rising_edge(dds_csb);
      exit when dds_csb = '1';
      sh := sh(254 downto 0) & dds_sdio; n := n + 1;
    end loop;
    instr := sh(n-1 downto n-16);
    a := to_integer(unsigned(instr(12 downto 0)));
    nbytes := (n - 16) / 8;
    for b in 0 to nbytes-1 loop                         -- MSB-first: address decrements
      ad_buf(a - b) <= sh(n-17-8*b downto n-24-8*b);
    end loop;
    if instr(14 downto 13) = "11" then n_roww <= n_roww + 1;
    else n_regw <= n_regw + 1; last_reg <= sh(23 downto 0); end if;
    assert instr(15) = '0' report "AD9912 model: unexpected READ" severity error;
    assert (n - 16) mod 8 = 0 report "AD9912 model: partial byte" severity error;
  end process;

  ad_update : process(dds_ioupdate) begin
    if rising_edge(dds_ioupdate) then
      act_ftw <= ad_buf(16#1AB#) & ad_buf(16#1AA#) & ad_buf(16#1A9#) &
                 ad_buf(16#1A8#) & ad_buf(16#1A7#) & ad_buf(16#1A6#);
      act_pow <= ad_buf(16#1AD#)(5 downto 0) & ad_buf(16#1AC#);
      n_upd <= n_upd + 1; t_upd <= now;
    end if;
  end process;

  -- ---------------- MCP4821 model ----------------
  dac_model : process
    variable sh : std_logic_vector(15 downto 0);
  begin
    wait until falling_edge(vga_cs);
    for i in 0 to 15 loop
      wait until rising_edge(vga_sck);
      sh := sh(14 downto 0) & vga_sci;
    end loop;
    wait until rising_edge(vga_cs);
    dac_in <= sh;
    assert vga_ldac = '1' report "MCP4821 model: LDAC low during a write" severity error;
  end process;
  dac_latch : process(vga_ldac) begin
    if falling_edge(vga_ldac) then dac_out <= dac_in; end if;
  end process;

  -- ---------------- stimulus / checks ----------------
  stim : process
    constant HALF : time := 20 ns;                       -- 25 MHz bus SCK
    variable fails : integer := 0;
    variable t0 : time;
    variable u0 : integer;

    procedure frame(b : std_logic_vector) is
      constant v : std_logic_vector(b'length-1 downto 0) := b;
    begin
      cs <= '0'; wait for HALF;
      for i in 0 to b'length-1 loop
        mosi <= v(b'length-1-i); wait for HALF;
        sck <= '1'; wait for HALF; sck <= '0';
      end loop;
      wait for HALF; cs <= '1'; wait for 300 ns;
    end procedure;

    procedure pulse(signal l : out std_logic) is         -- 120 ns pulse (3 x 40 ns)
    begin l <= '1'; wait for 120 ns; l <= '0'; end procedure;

    procedure check_live(name : string; r : std_logic_vector(87 downto 0)) is
    begin
      if act_ftw /= r(87 downto 40) or act_pow /= r(39 downto 26) or
         dac_out /= ("0011" & r(23 downto 12)) or rf_main_sw /= r(0) then
        report name & ": FAIL live state  ftw=" & to_hstring(act_ftw) & " pow=" &
               to_hstring(act_pow) & " dac=" & to_hstring(dac_out) & " rf=" &
               std_logic'image(rf_main_sw) severity error;
        fails := fails + 1;
      else
        report name & ": ok (ftw=" & to_hstring(act_ftw) & ", rf=" & std_logic'image(rf_main_sw) & ")";
      end if;
    end procedure;

    procedure check(name : string; cond : boolean) is
    begin
      if cond then report name & ": ok";
      else report name & ": FAIL" severity error; fails := fails + 1; end if;
    end procedure;
  begin
    -- master drives the broadcast lines low from the start (like a running XEM7305)
    stepnext <= '0'; ramreset <= '0';

    -- power-up: POR (~0.42 ms) + AD9912 init + apply row 0 (all-zero table)
    wait for 600 us;
    check("P1 init: 3 AD9912 register writes", n_regw = 3);
    check("P2 init: 0x0010=D0 / FSC=0x200",
          ad_buf(16#010#) = x"D0" and ad_buf(16#40C#) = x"02" and ad_buf(16#40B#) = x"00");
    check_live("P3 power-up applies empty row 0 (RF open)", (87 downto 0 => '0'));

    -- write rows 0..3, then RESET frame -> row 0 live, row 1 preloaded
    frame("000" & ADDR & x"01" & x"0000" & R0 & R1 & R2 & R3);
    frame("000" & ADDR & x"02");
    wait for 10 us;
    check_live("T1 RESET frame -> row 0", R0);
    check("T1b row 1 preloaded in AD9912 buffer (not live)",
          ad_buf(16#1AB#) & ad_buf(16#1AA#) & ad_buf(16#1A9#) & ad_buf(16#1A8#) &
          ad_buf(16#1A7#) & ad_buf(16#1A6#) = R1(87 downto 40));

    -- STEPNEXT -> row 1, latency check
    u0 := n_upd; t0 := now;
    pulse(stepnext);
    wait for 4880 ns;                                    -- next step exactly 5 us later
    check_live("T2 STEPNEXT -> row 1", R1);
    report "T2 STEPNEXT->IO_UPDATE latency = " & time'image(t_upd - t0);
    check("T2b latency < 100 ns", n_upd = u0 + 1 and t_upd - t0 < 100 ns);

    -- another step after > 5 us -> row 2 (RF off)
    pulse(stepnext); wait for 10 us;
    check_live("T3 STEPNEXT -> row 2 (RF off)", R2);
    check("T3b no overrun at the 5 us minimum spacing (LED r2 off)", leds(7) = '1');

    -- two steps 1 us apart: second arrives while preloading -> late, not lost
    pulse(stepnext); wait for 1 us;
    pulse(stepnext); wait for 10 us;
    check_live("T4 fast double step -> row 4 (= empty row)", (87 downto 0 => '0'));
    check("T4b overrun flagged (LED r2 on)", leds(7) = '0');

    -- RAMRESET line -> row 0
    pulse(ramreset); wait for 10 us;
    check_live("T5 RAMRESET -> row 0", R0);

    -- WRITE_REG 0x040B = 0x55 -> register written, current row re-applied
    u0 := n_regw;
    frame("000" & ADDR & x"04" & x"040B" & x"55");
    wait for 10 us;
    check("T6 WRITE_REG reached the AD9912", n_regw = u0 + 1 and ad_buf(16#40B#) = x"55");
    check_live("T6b row 0 still live after WRITE_REG", R0);

    -- STEP frame -> row 1
    frame("000" & ADDR & x"03"); wait for 10 us;
    check_live("T7 STEP frame -> row 1", R1);

    -- frame for another board -> nothing changes; broadcast rewrite of row 2 then step
    frame("000" & "00110" & x"01" & x"0002" & R9); wait for 10 us;
    check_live("T8 other board's frame ignored", R1);
    frame("000" & "11111" & x"01" & x"0002" & R9); wait for 10 us;   -- preloaded row 2 overwritten
    pulse(stepnext); wait for 10 us;
    check_live("T9 rewritten preloaded row is what gets stepped to", R9);

    if fails = 0 then report "tb_dds_top: ALL TESTS PASSED";
    else report "tb_dds_top: " & integer'image(fails) & " FAILURE(S)" severity error; end if;
    std.env.stop;
  end process;
end architecture;
