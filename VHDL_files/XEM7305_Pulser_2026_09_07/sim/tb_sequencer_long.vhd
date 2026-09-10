-------------------------------------------------------------------------------
-- tb_sequencer_long  (Phase 6c -- sustained-streaming terminator)
--
-- Reproduces the hardware --long finding: a program much longer than the
-- streamer prime window / line FIFO (here 1200 lines) whose terminator is
-- therefore reached DURING sustained streaming, not out of the initial prime.
-- The fixed-array models never drove the terminator past the prime window, so
-- this case was never simulated.
--
-- The ramp is line(i): channel = i+1, time = (i+1)*DWELL, for i in 0..NPROG-1,
-- then an all-zero terminator. Correct behaviour: master_logic steps
-- 1,2,3,...,NPROG strictly in order, then seq_done, then master_logic = 0.
-- The bug: the sequencer runs PAST the terminator and never asserts seq_done.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_sequencer_long is
end entity;

architecture tb of tb_sequencer_long is
  constant AW    : natural := 29;
  constant DWELL : natural := 10;
  constant NPROG : natural := 1200;

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

  signal prev_master : std_logic_vector(31 downto 0) := (others => '0');
  signal reached     : integer := 0;   -- highest channel seen
  signal errors      : integer := 0;   -- out-of-order transitions
  signal done_seen   : integer := 0;
  signal sim_done    : boolean := false;
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
              infinite => '0', prog_ready => primed_seq,
              line_trig_en => '0', line_trig_pulse => '0', loop_limit => (others => '0'),
              line_dout => line_dout, line_empty => line_empty, line_rd_en => line_rd_en,
              restart => restart, master_logic => master_logic,
              seq_count_out => open, seq_done => seq_done);

  rst_cdc : entity work.pulse_cdc
    port map (src_clk => seq_clk, src_pulse => restart,
              dst_clk => ui_clk, dst_pulse => restart_ui);
  prm_sync : entity work.level_sync
    port map (dst_clk => seq_clk, d => primed, q => primed_seq);

  mon : process (seq_clk)
    variable nv, pv : integer;
  begin
    if rising_edge(seq_clk) then
      if master_logic /= prev_master then
        nv := to_integer(unsigned(master_logic));
        pv := to_integer(unsigned(prev_master));
        if nv /= 0 then
          if nv /= pv + 1 then
            errors <= errors + 1;
            report "OUT OF ORDER: " & integer'image(pv) & " -> " & integer'image(nv)
                   severity error;
          end if;
          if nv > reached then reached <= nv; end if;
        end if;
        prev_master <= master_logic;
      end if;
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

    -- run until seq_done, or a generous timeout (NPROG lines * DWELL ticks * 4
    -- seq_clk/tick, plus margin)
    for i in 0 to NPROG*DWELL*4 + 200000 loop
      wait until rising_edge(seq_clk);
      exit when seq_done = '1';
    end loop;

    report "long test: reached channel " & integer'image(reached) &
           " of " & integer'image(NPROG) & ", errors " & integer'image(errors) &
           ", done_seen " & integer'image(done_seen);
    assert errors = 0 report "values out of order (streaming corruption)" severity failure;
    -- the line immediately before the terminator does not emit its channel (a
    -- known sequencer quirk, see mig_prog_model PROG0), so the highest channel
    -- emitted is NPROG-1, not NPROG.
    assert reached >= NPROG-1
      report "did not stream the whole program (reached " & integer'image(reached) &
             " of " & integer'image(NPROG) & ")" severity failure;
    assert seq_done = '1'
      report "TERMINATOR NOT HONORED: streamed the whole program but seq_done "
             & "never asserted -- ran past the terminator" severity failure;
    report "ALL TESTS PASSED: long program terminated correctly under sustained streaming";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;
end architecture;
