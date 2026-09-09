-------------------------------------------------------------------------------
-- tb_sequencer_loop  (Phase 6c milestone 3 -- infinite-loop / restart path)
--
-- Same wiring as tb_sequencer but with infinite loop enabled. Verifies the
-- sequencer<->streamer loop-back integration: on the terminator the sequencer
-- pulses `restart`, the streamer drains + rewinds + re-primes, and the
-- sequencer reloads from line 0 -- so the program repeats. Checks that the
-- program runs at least 3 times (master_logic returns to 0x1), that `restart`
-- fires each loop, and that seq_done never asserts.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_sequencer_loop is
end entity;

architecture tb of tb_sequencer_loop is
  constant AW : natural := 29;
  signal ui_clk, seq_clk : std_logic := '0';
  signal ui_rst  : std_logic := '1';
  signal run       : std_logic := '0';
  signal restart   : std_logic;    -- sequencer output (seq_clk)
  signal restart_ui: std_logic;    -- synchronized into ui_clk for the streamer
  signal primed    : std_logic;    -- streamer output (ui_clk)
  signal primed_seq: std_logic;    -- synchronized into seq_clk for the sequencer
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

  signal prev_master : std_logic_vector(31 downto 0) := (others => '0');
  signal loops       : integer := 0;   -- times master returned to 0x1
  signal restart_cnt : integer := 0;
  signal done_seen   : integer := 0;
  signal sim_done    : boolean := false;
begin
  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  streamer : entity work.ddr3_line_streamer
    generic map (ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
                 SCRATCH_XOR_BIT => 25, PRIME_BEATS => 4,
                 HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
    port map (ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
              run => run, restart => restart_ui, primed => primed,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid,
              line_rd_en => line_rd_en, line_dout => line_dout, line_empty => line_empty,
              dbg_retry_count => dbg_retry, dbg_hb_count => dbg_hb);

  mig : entity work.mig_prog_model
    generic map (ADDR_WIDTH => AW, ADDR_INC => 8, READ_LATENCY => 24)
    port map (ui_clk => ui_clk, ui_rst => ui_rst,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid);

  seq : entity work.pulse_sequencer
    port map (clk => seq_clk, reset => seq_reset, start => seq_start,
              infinite => '1', prog_ready => primed_seq,
              line_trig_en => '0', line_trig_pulse => '0', loop_limit => (others => '0'),
              line_dout => line_dout, line_empty => line_empty, line_rd_en => line_rd_en,
              restart => restart, master_logic => master_logic,
              seq_count_out => open, seq_done => seq_done);

  -- CDC: restart pulse seq_clk -> ui_clk, and primed level ui_clk -> seq_clk
  rst_cdc : entity work.pulse_cdc
    port map (src_clk => seq_clk, src_pulse => restart,
              dst_clk => ui_clk, dst_pulse => restart_ui);
  prm_sync : entity work.level_sync
    port map (dst_clk => seq_clk, d => primed, q => primed_seq);

  mon : process (seq_clk)
  begin
    if rising_edge(seq_clk) then
      if master_logic /= prev_master then
        if master_logic = x"00000001" then loops <= loops + 1; end if;
        prev_master <= master_logic;
      end if;
      if restart = '1' then restart_cnt <= restart_cnt + 1; end if;
      if seq_done = '1' then done_seen <= done_seen + 1; end if;
    end if;
  end process;

  stim : process
  begin
    ui_rst <= '1'; seq_reset <= '1'; run <= '0'; seq_start <= '0';
    for i in 0 to 9 loop wait until rising_edge(ui_clk); end loop;
    ui_rst <= '0'; run <= '1';
    for i in 0 to 5000 loop wait until rising_edge(ui_clk); exit when primed = '1'; end loop;
    assert primed = '1' report "never primed" severity failure;
    wait until rising_edge(seq_clk); seq_reset <= '0';
    wait until rising_edge(seq_clk); seq_start <= '1';

    -- run long enough for several loop iterations
    for i in 0 to 200000 loop
      wait until rising_edge(seq_clk);
      exit when loops >= 3;
    end loop;

    report "loops(master->0x1)=" & integer'image(loops) &
           " restart_pulses=" & integer'image(restart_cnt) &
           " done_seen=" & integer'image(done_seen);
    assert loops >= 3 report "program did not loop (restart/reload path broken)" severity failure;
    assert restart_cnt >= 2 report "restart never pulsed to the streamer" severity failure;
    assert done_seen = 0 report "seq_done asserted in infinite mode" severity failure;
    report "ALL TESTS PASSED: infinite-loop restart/reload path works";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;
end architecture;
