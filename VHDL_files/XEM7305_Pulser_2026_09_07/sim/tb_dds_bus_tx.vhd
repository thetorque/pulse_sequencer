-- tb_dds_bus_tx.vhd -- Phase 4 DDS bus master, checked against the REAL slave receiver.
--
-- Chain: host byte stream (length-prefixed records, packed LSB-first into 32-bit words)
--        -> FWFT FIFO model -> dds_bus_tx (clk_100) -> backplane wires
--        -> bus_rx (DDS board receiver, ../../DDS_ECP5_2026_10_19/bus_rx.vhd, ~155 MHz)
-- Checks every row bus_rx writes, the RESET/STEP strobes, padding records, a FIFO that
-- starves mid-frame (bus must pause, not corrupt), and the STEPNEXT/RAMRESET lines.
-- Ends with "tb_dds_bus_tx: ALL TESTS PASSED".

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_dds_bus_tx is end entity;

architecture sim of tb_dds_bus_tx is
  constant NW : integer := 64;                         -- FIFO model capacity (words)
  type word_arr is array (0 to NW-1) of std_logic_vector(31 downto 0);
  type byte_arr is array (natural range <>) of std_logic_vector(7 downto 0);

  signal clk, clk_s : std_logic := '0';
  signal rst : std_logic := '1';

  -- FIFO model (FWFT)
  signal mem    : word_arr;
  signal wr_ptr, rd_ptr : integer := 0;
  signal gate   : integer := NW;                       -- words released to the reader
  signal fdout  : std_logic_vector(31 downto 0);
  signal fempty, frd : std_logic;

  signal seq_step, seq_reset, trig_step, trig_reset : std_logic := '0';
  signal sck, mosi, cs, stp, rrs, fact : std_logic;
  signal nsent : std_logic_vector(15 downto 0);
  signal idle  : std_logic;
  signal busy_seen : boolean := false;

  -- receiver side
  signal we, rows_written, cmd_reset, cmd_step, reg_we, frame_err : std_logic;
  signal waddr : std_logic_vector(12 downto 0);
  signal wdata : std_logic_vector(87 downto 0);
  signal reg_addr : std_logic_vector(15 downto 0);
  signal reg_data : std_logic_vector(7 downto 0);
  type row_log is array (0 to 15) of std_logic_vector(87 downto 0);
  signal log_d : row_log;
  signal log_a : row_log;
  signal n_we, n_rst, n_step, n_err, n_rw : integer := 0;
  signal n_stp_edges, n_rr_edges : integer := 0;
  signal stp_w, rr_w : time := 0 ns;                   -- last measured pulse widths

  function mkrow(k : integer) return std_logic_vector is
    variable r : std_logic_vector(87 downto 0);
  begin
    for b in 0 to 10 loop
      r(87-8*b downto 80-8*b) := std_logic_vector(to_unsigned((k*53 + b*7 + 3) mod 256, 8));
    end loop;
    return r;
  end function;
begin
  clk   <= not clk   after 5 ns;                       -- clk_100
  clk_s <= not clk_s after 3.225 ns;                   -- slave ~155 MHz

  -- FWFT FIFO model: dout = head word while (rd_ptr < wr_ptr and rd_ptr < gate)
  fempty <= '0' when rd_ptr < wr_ptr and rd_ptr < gate else '1';
  fdout  <= mem(rd_ptr mod NW) when fempty = '0' else (others => 'X');
  process(clk) begin
    if rising_edge(clk) then
      if frd = '1' then
        assert fempty = '0' report "FIFO model: read while empty" severity failure;
        rd_ptr <= rd_ptr + 1;
      end if;
    end if;
  end process;

  dut : entity work.dds_bus_tx
    port map ( clk => clk, rst => rst, fifo_dout => fdout, fifo_empty => fempty, fifo_rd_en => frd,
               seq_step => seq_step, seq_reset => seq_reset,
               trig_step => trig_step, trig_reset => trig_reset,
               bp_sck => sck, bp_mosi => mosi, bp_cs => cs, bp_step => stp, bp_reset => rrs,
               frame_active => fact, frames_sent => nsent, idle => idle );
  process(clk) begin
    if rising_edge(clk) and rst = '0' and idle = '0' then busy_seen <= true; end if;
  end process;

  rx : entity work.bus_rx
    generic map ( ADDR_W => 13, DATA_W => 88 )
    port map ( clk => clk_s, rst => rst, bp_sck => sck, bp_mosi => mosi, bp_cs => cs,
               board_addr => "00101", we => we, waddr => waddr, wdata => wdata,
               rows_written => rows_written, cmd_reset => cmd_reset, cmd_step => cmd_step,
               reg_we => reg_we, reg_addr => reg_addr, reg_data => reg_data, frame_err => frame_err );

  mon : process(clk_s) begin
    if rising_edge(clk_s) then
      if we = '1' then
        log_d(n_we mod 16) <= wdata;
        log_a(n_we mod 16) <= std_logic_vector(resize(unsigned(waddr), 88));
        n_we <= n_we + 1;
      end if;
      if cmd_reset = '1' then n_rst <= n_rst + 1; end if;
      if cmd_step = '1' then n_step <= n_step + 1; end if;
      if frame_err = '1' then n_err <= n_err + 1; end if;
      if rows_written = '1' then n_rw <= n_rw + 1; end if;
    end if;
  end process;

  linemon : process
    variable t0 : time;
  begin
    wait until rising_edge(stp) or rising_edge(rrs);
    t0 := now;
    if stp = '1' then
      wait until falling_edge(stp); stp_w <= now - t0; n_stp_edges <= n_stp_edges + 1;
    else
      wait until falling_edge(rrs); rr_w <= now - t0; n_rr_edges <= n_rr_edges + 1;
    end if;
  end process;

  stim : process
    variable stream : byte_arr(0 to 4*NW-1);
    variable nb : integer := 0;
    variable fails : integer := 0;

    procedure put(b : std_logic_vector(7 downto 0)) is
    begin stream(nb) := b; nb := nb + 1; end procedure;

    procedure put_vec(v : std_logic_vector) is                -- whole bytes, MSB first
      constant c : std_logic_vector(v'length-1 downto 0) := v;
    begin
      for i in 0 to v'length/8 - 1 loop put(c(v'length-1-8*i downto v'length-8-8*i)); end loop;
    end procedure;

    procedure add_record(frame : std_logic_vector) is            -- LEN16 + frame
    begin
      put_vec(std_logic_vector(to_unsigned(frame'length/8, 16)));
      put_vec(frame);
    end procedure;

    procedure flush_to_fifo is                                -- pad to whole words, LSB-first
      variable w : std_logic_vector(31 downto 0);
    begin
      while nb mod 4 /= 0 loop put(x"00"); end loop;
      for i in 0 to nb/4 - 1 loop
        w := stream(4*i+3) & stream(4*i+2) & stream(4*i+1) & stream(4*i);
        mem((wr_ptr + i) mod NW) <= w;
      end loop;
      wr_ptr <= wr_ptr + nb/4;
      nb := 0;
    end procedure;

    procedure check(name : string; cond : boolean) is
    begin
      if cond then report name & ": ok";
      else report name & ": FAIL" severity error; fails := fails + 1; end if;
    end procedure;
  begin
    wait for 100 ns; rst <= '0'; wait for 100 ns;
    check("T0 idle after reset with an empty FIFO", idle = '1' and not busy_seen);

    -- T1: WRITE_ROWS (2 rows, board 5) + padding record + RESET (broadcast)
    add_record(x"05" & x"01" & x"0010" & mkrow(1) & mkrow(2));
    put(x"00"); put(x"00");                                  -- LEN=0 padding record
    add_record(x"1F" & x"02");
    flush_to_fifo;
    wait for 20 us;
    check("T1a 2 rows written", n_we = 2 and n_rw = 1);
    check("T1b row data/addr", log_d(0) = mkrow(1) and log_d(1) = mkrow(2) and
                                unsigned(log_a(0)) = 16 and unsigned(log_a(1)) = 17);
    check("T1c RESET frame decoded", n_rst = 1);
    check("T1d no frame errors", n_err = 0);
    check("T1e frames_sent = 2", unsigned(nsent) = 2);
    check("T1f idle went low while sending, high again after", busy_seen and idle = '1');

    -- T2: FIFO starves mid-frame: release words one at a time, 2 us apart
    gate <= rd_ptr;
    wait for 1 ns;
    add_record(x"05" & x"01" & x"0100" & mkrow(7) & mkrow(8) & mkrow(9));
    add_record(x"05" & x"03");                                  -- STEP
    add_record(x"1F" & x"00" & x"00");    -- NOP filler: end on a record boundary, as pack() does
    flush_to_fifo;
    for i in 0 to 12 loop
      wait for 2 us; gate <= gate + 1;
    end loop;
    gate <= NW * 1000;
    wait for 20 us;
    check("T2a starved frame: 3 rows intact", n_we = 5 and log_d(2) = mkrow(7) and
                                              log_d(3) = mkrow(8) and log_d(4) = mkrow(9));
    check("T2b STEP after starved frame", n_step = 1);
    check("T2c still no frame errors", n_err = 0);
    check("T2d idle after the starved frame drained", idle = '1');

    -- T3: broadcast lines
    wait until rising_edge(clk); trig_step <= '1';
    wait until rising_edge(clk); trig_step <= '0';
    wait for 1 us;
    check("T3a trigger STEPNEXT pulse ~120 ns", n_stp_edges = 1 and stp_w >= 100 ns and stp_w <= 140 ns);
    wait until rising_edge(clk); trig_reset <= '1';
    wait until rising_edge(clk); trig_reset <= '0';
    wait for 1 us;
    check("T3b trigger RAMRESET pulse ~120 ns", n_rr_edges = 1 and rr_w >= 100 ns and rr_w <= 140 ns);
    seq_step <= '1'; wait for 120 ns; seq_step <= '0'; wait for 1 us;
    check("T3c sequencer channel 18 -> STEPNEXT", n_stp_edges = 2 and stp_w >= 110 ns and stp_w <= 130 ns);
    seq_reset <= '1'; wait for 120 ns; seq_reset <= '0'; wait for 1 us;
    check("T3d sequencer channel 19 -> RAMRESET", n_rr_edges = 2);

    if fails = 0 then report "tb_dds_bus_tx: ALL TESTS PASSED";
    else report "tb_dds_bus_tx: " & integer'image(fails) & " FAILURE(S)" severity error; end if;
    std.env.stop;
  end process;
end architecture;
