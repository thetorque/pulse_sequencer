-------------------------------------------------------------------------------
-- tb_streamer_throughput  (Phase 6c milestone 5 -- starvation analysis)
--
-- Measures the ddr3_line_streamer's SUSTAINED line-delivery rate: a greedy
-- consumer pops a line on every seq_clk cycle data is available, so once the
-- prefetch FIFO has drained the steady-state pop rate equals the streamer's
-- production rate. That rate is the minimum dwell the sequencer can sustain
-- indefinitely; shorter dwells only survive as a burst bounded by FIFO depth.
--
-- The one-at-a-time read engine (issue -> wait full read latency -> next)
-- produces one 128-bit beat = 2 lines per (~READ_LATENCY + handshake) ui_clk,
-- so this quantifies whether that is fast enough or whether pipelined
-- (multiple-outstanding) reads are needed before integrating into the FSM.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_streamer_throughput is
end entity;

architecture tb of tb_streamer_throughput is
  constant AW : natural := 29;

  signal ui_clk  : std_logic := '0';
  signal seq_clk : std_logic := '0';
  signal ui_rst  : std_logic := '1';
  signal run     : std_logic := '0';
  signal primed  : std_logic;

  signal app_addr : std_logic_vector(AW-1 downto 0);
  signal app_cmd  : std_logic_vector(2 downto 0);
  signal app_en   : std_logic;
  signal app_rdy  : std_logic;
  signal app_rd_data       : std_logic_vector(127 downto 0);
  signal app_rd_data_valid : std_logic;

  signal line_rd_en : std_logic := '0';
  signal line_dout  : std_logic_vector(63 downto 0);
  signal line_empty : std_logic;
  signal dbg_retry_count, dbg_hb_count : std_logic_vector(7 downto 0);

  signal measuring : std_logic := '0';
  signal clr_pops  : std_logic := '0';
  signal pops      : integer := 0;
  signal sim_done  : boolean := false;

  constant SEQ_PERIOD_NS : real := 10.0;
  constant WINDOW_NS     : real := 200000.0;   -- 200 us measurement window
begin

  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  dut : entity work.ddr3_line_streamer
    generic map (ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
                 SCRATCH_XOR_BIT => 25, PRIME_BEATS => 8,
                 HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
    port map (ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
              run => run, restart => '0', primed => primed,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid,
              line_rd_en => line_rd_en, line_dout => line_dout, line_empty => line_empty,
              dbg_retry_count => dbg_retry_count, dbg_hb_count => dbg_hb_count);

  mig : entity work.mig_read_model
    generic map (ADDR_WIDTH => AW, ADDR_INC => 8, READ_LATENCY => 24,
                 DROP_EVERY => 0, STALL_MASK => 0)
    port map (ui_clk => ui_clk, ui_rst => ui_rst,
              app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
              app_rdy => app_rdy, app_rd_data => app_rd_data,
              app_rd_data_valid => app_rd_data_valid);

  -- greedy consumer: pop whenever a line is available
  line_rd_en <= '1' when (measuring = '1' and line_empty = '0') else '0';

  count_proc : process (seq_clk)
  begin
    if rising_edge(seq_clk) then
      if clr_pops = '1' then
        pops <= 0;
      elsif measuring = '1' and line_empty = '0' then
        pops <= pops + 1;   -- one line consumed this cycle
      end if;
    end if;
  end process;

  stim : process
    variable rate_lines_per_us : real;
    variable min_dwell_ns      : real;
  begin
    ui_rst <= '1'; run <= '0';
    for i in 0 to 9 loop wait until rising_edge(ui_clk); end loop;
    ui_rst <= '0'; wait until rising_edge(ui_clk);
    run <= '1';
    for i in 0 to 5000 loop wait until rising_edge(ui_clk); exit when primed = '1'; end loop;

    -- greedily drain for a while first so the initial FIFO buffer is gone and
    -- we measure steady-state PRODUCTION, not the buffered burst.
    measuring <= '1';
    wait for 50 us;              -- drain the prefetch buffer to steady state
    clr_pops <= '1';             -- reset the counter for the measurement window
    wait until rising_edge(seq_clk); wait until rising_edge(seq_clk);
    clr_pops <= '0';
    wait for WINDOW_NS * 1 ns;   -- measure

    rate_lines_per_us := real(pops) / (WINDOW_NS / 1000.0);
    min_dwell_ns      := 1000.0 / rate_lines_per_us;
    report "THROUGHPUT: sustained " & real'image(rate_lines_per_us) &
           " lines/us  => min sustainable dwell ~ " & real'image(min_dwell_ns) &
           " ns/line  (popped " & integer'image(pops) & " in " &
           integer'image(integer(WINDOW_NS)) & " ns)";
    report "  (FIFO depth 256 beats = 512 lines buffers a burst of shorter " &
           "dwells; sustained rate is set by the read engine, not FIFO depth)";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
