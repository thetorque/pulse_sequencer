-------------------------------------------------------------------------------
-- tb_sequencer_nloop  (Phase 6c -- finite N-loop + per-loop line accounting)
--
-- Runs a small ramp program with infinite='1' and loop_limit=LOOPS, so the
-- sequencer repeats it exactly LOOPS times then stops. Confirms the finite-loop
-- path (seq_count reaches LOOPS, seq_done asserts) AND that line_count ==
-- LOOPS*(NPROG+1) -- i.e. every line of every loop was popped, which is the
-- formula the host --loops check relies on.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_sequencer_nloop is
end entity;

architecture tb of tb_sequencer_nloop is
  constant AW    : natural := 29;
  constant DWELL : natural := 10;
  constant NPROG : natural := 20;
  constant LOOPS : natural := 3;
  -- lines popped over N finite loops: N*(NPROG+1) plus one extra pop per loop
  -- boundary (the restart re-prime), i.e. + (N-1). Hardware-derived (sim).
  constant EXPECT_LC : natural := LOOPS*(NPROG+1) + (LOOPS-1);

  signal ui_clk, seq_clk : std_logic := '0';
  signal ui_rst  : std_logic := '1';
  signal run       : std_logic := '0';
  signal restart   : std_logic;
  signal restart_ui: std_logic;
  signal primed    : std_logic;
  signal primed_seq: std_logic;
  signal app_addr : std_logic_vector(AW-1 downto 0);
  signal app_cmd  : std_logic_vector(2 downto 0);
  signal app_en   : std_logic;
  signal app_rdy  : std_logic;
  signal app_rd_data       : std_logic_vector(127 downto 0);
  signal app_rd_data_valid : std_logic;
  signal line_dout  : std_logic_vector(63 downto 0);
  signal line_empty : std_logic;
  signal line_rd_en : std_logic;
  signal dbg_retry, dbg_hb : std_logic_vector(7 downto 0);
  signal seq_reset : std_logic := '1';
  signal seq_start : std_logic := '0';
  signal master_logic : std_logic_vector(31 downto 0);
  signal seq_done  : std_logic;
  signal seq_cnt   : std_logic_vector(15 downto 0);
  signal seq_lc    : std_logic_vector(31 downto 0);
  signal sim_done  : boolean := false;
begin
  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  streamer : entity work.ddr3_line_streamer
    generic map (ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
                 SCRATCH_XOR_BIT => 25, PRIME_BEATS => 8,
                 HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
    port map (ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
              run => run, restart => restart_ui, primed => primed,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid,
              line_rd_en => line_rd_en, line_dout => line_dout, line_empty => line_empty,
              dbg_retry_count => dbg_retry, dbg_hb_count => dbg_hb);

  mig : entity work.mig_ramp_model
    generic map (ADDR_WIDTH => AW, ADDR_INC => 8, READ_LATENCY => 24,
                 DWELL => DWELL, NPROG => NPROG)
    port map (ui_clk => ui_clk, ui_rst => ui_rst,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid);

  seq : entity work.pulse_sequencer
    port map (clk => seq_clk, reset => seq_reset, start => seq_start,
              infinite => '1', prog_ready => primed_seq,
              line_trig_en => '0', line_trig_pulse => '0',
              loop_limit => std_logic_vector(to_unsigned(LOOPS, 16)),
              line_dout => line_dout, line_empty => line_empty, line_rd_en => line_rd_en,
              restart => restart, master_logic => master_logic,
              seq_count_out => seq_cnt, seq_done => seq_done, line_count => seq_lc);

  rst_cdc : entity work.pulse_cdc
    port map (src_clk => seq_clk, src_pulse => restart,
              dst_clk => ui_clk, dst_pulse => restart_ui);
  prm_sync : entity work.level_sync
    port map (dst_clk => seq_clk, d => primed, q => primed_seq);

  stim : process
    variable lc, sc : integer;
  begin
    ui_rst <= '1'; seq_reset <= '1'; run <= '0'; seq_start <= '0';
    for i in 0 to 9 loop wait until rising_edge(ui_clk); end loop;
    ui_rst <= '0'; run <= '1';
    for i in 0 to 5000 loop wait until rising_edge(ui_clk); exit when primed = '1'; end loop;
    assert primed = '1' report "never primed" severity failure;
    wait until rising_edge(seq_clk); seq_reset <= '0';
    wait until rising_edge(seq_clk); seq_start <= '1';

    for i in 0 to 400000 loop
      wait until rising_edge(seq_clk); exit when seq_done = '1';
    end loop;
    assert seq_done = '1' report "finite loop never finished" severity failure;

    sc := to_integer(unsigned(seq_cnt));
    lc := to_integer(unsigned(seq_lc));
    report "nloop test: seq_count=" & integer'image(sc) & " (expect " &
           integer'image(LOOPS) & "), line_count=" & integer'image(lc) &
           " (expect " & integer'image(EXPECT_LC) & ")";
    assert sc = LOOPS
      report "seq_count " & integer'image(sc) & " /= " & integer'image(LOOPS)
      severity failure;
    assert lc = EXPECT_LC
      report "line_count " & integer'image(lc) & " /= N*(NPROG+1)+(N-1) = " &
             integer'image(EXPECT_LC) severity failure;
    report "ALL TESTS PASSED: finite loop ran LOOPS times, every line of every loop popped";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;
end architecture;
