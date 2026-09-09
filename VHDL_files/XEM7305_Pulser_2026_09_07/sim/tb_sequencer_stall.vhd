-------------------------------------------------------------------------------
-- tb_sequencer_stall  (Phase 6c milestone 3 -- underrun / stall robustness)
--
-- Runs the 11-pulse short-dwell stress program (each line held one 40 ns tick)
-- with a small prime buffer, so the sequencer consumes lines faster than the
-- streamer produces them and the FIFO underruns. Verifies the sequencer's
-- FAILURE MODE is safe: it STALLS (holds the current state until the next line
-- arrives) so the emitted channels are still 1,2,...,11 in strict order --
-- timing stretches, but never garbage or out-of-order. Confirms at least one
-- dwell was stretched beyond one tick (i.e. a stall actually happened).
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_sequencer_stall is
end entity;

architecture tb of tb_sequencer_stall is
  constant AW : natural := 29;
  signal ui_clk, seq_clk : std_logic := '0';
  signal ui_rst  : std_logic := '1';
  signal run     : std_logic := '0';
  signal restart : std_logic;
  signal primed  : std_logic;
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
  signal held        : integer := 0;
  signal max_held    : integer := 0;
  signal reached     : integer := 0;
  signal errors      : integer := 0;
  signal sim_done    : boolean := false;
begin
  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  streamer : entity work.ddr3_line_streamer
    generic map (ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
                 SCRATCH_XOR_BIT => 25, PRIME_BEATS => 2,      -- small prime -> easy underrun
                 HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
    port map (ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
              run => run, restart => restart, primed => primed,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid,
              line_rd_en => line_rd_en, line_dout => line_dout, line_empty => line_empty,
              dbg_retry_count => dbg_retry, dbg_hb_count => dbg_hb);

  mig : entity work.mig_prog_model
    generic map (ADDR_WIDTH => AW, ADDR_INC => 8, READ_LATENCY => 24, PROG_SEL => 1)
    port map (ui_clk => ui_clk, ui_rst => ui_rst,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid);

  seq : entity work.pulse_sequencer
    port map (clk => seq_clk, reset => seq_reset, start => seq_start,
              infinite => '0', prog_ready => primed,
              line_trig_en => '0', line_trig_pulse => '0', loop_limit => (others => '0'),
              line_dout => line_dout, line_empty => line_empty, line_rd_en => line_rd_en,
              restart => restart, master_logic => master_logic,
              seq_count_out => open, seq_done => seq_done);

  mon : process (seq_clk)
    variable nv, pv : integer;
  begin
    if rising_edge(seq_clk) then
      if master_logic /= prev_master then
        nv := to_integer(unsigned(master_logic));
        pv := to_integer(unsigned(prev_master));
        if held > max_held then max_held <= held; end if;
        if nv /= 0 then
          if nv /= pv + 1 then
            errors <= errors + 1;
            report "OUT OF ORDER: " & integer'image(pv) & " -> " & integer'image(nv)
                   severity error;
          end if;
          if nv > reached then reached <= nv; end if;
        end if;
        held <= 0;
        prev_master <= master_logic;
      else
        held <= held + 1;
      end if;
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

    for i in 0 to 200000 loop
      wait until rising_edge(seq_clk); exit when seq_done = '1';
    end loop;
    assert seq_done = '1' report "never finished (stall deadlocked?)" severity failure;
    for i in 0 to 10 loop wait until rising_edge(seq_clk); end loop;

    report "stall test: reached channel " & integer'image(reached) &
           ", max dwell " & integer'image(max_held+1) & " cycles, errors " &
           integer'image(errors);
    assert errors = 0 report "values out of order under underrun" severity failure;
    assert reached >= 11 report "did not emit the whole program" severity failure;
    assert (max_held + 1) > 4
      report "no stall occurred (dwell never exceeded 1 tick) -- test did not underrun"
      severity failure;
    report "ALL TESTS PASSED: underrun stalls safely (values in order, timing stretched)";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;
end architecture;
