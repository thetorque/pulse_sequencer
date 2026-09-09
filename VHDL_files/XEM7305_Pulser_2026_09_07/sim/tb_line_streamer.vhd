-------------------------------------------------------------------------------
-- tb_line_streamer  (Phase 6c milestone 1 testbench)
--
-- Drives ddr3_line_streamer with a behavioural MIG read model and a consumer
-- that pops 64-bit lines on seq_clk (the sequencer's clock) and checks:
--   * lines arrive strictly in order (each line encodes its own index),
--   * no starvation at a representative consume rate once primed,
--   * the keep-warm heartbeat fires while the FIFO is full/idle,
--   * loop-back (restart) rewinds the stream to line 0.
--
-- Run:  ghdl -a --std=08 line_fifo_128x64.vhd mig_read_model.vhd \
--            ddr3_line_streamer.vhd tb_line_streamer.vhd
--       ghdl -e --std=08 tb_line_streamer ; ghdl -r --std=08 tb_line_streamer
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_line_streamer is
end entity;

architecture tb of tb_line_streamer is
  constant AW : natural := 29;

  signal ui_clk  : std_logic := '0';
  signal seq_clk : std_logic := '0';
  signal ui_rst  : std_logic := '1';

  signal run     : std_logic := '0';
  signal restart : std_logic := '0';
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

  signal dbg_retry_count : std_logic_vector(7 downto 0);
  signal dbg_hb_count    : std_logic_vector(7 downto 0);

  -- consumer control / results
  signal consume_en   : std_logic := '0';
  signal dwell_cycles : integer := 30;      -- seq_clk cycles between pops
  signal expected     : integer := 0;
  signal reset_expect : std_logic := '0';   -- pulse: force expected back to 0
  signal lines_popped : integer := 0;
  signal errors       : integer := 0;
  signal starv        : integer := 0;

  signal sim_done : boolean := false;

  type cstate_t is (C_WAIT, C_REQ, C_CAP);
  signal cstate : cstate_t := C_WAIT;
  signal dwell_ctr : integer := 0;
begin

  -- 81.25 MHz ui_clk (period 12.308 ns) and 100 MHz seq_clk (10 ns)
  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  dut : entity work.ddr3_line_streamer
    generic map (
      ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
      SCRATCH_XOR_BIT => 25, PRIME_BEATS => 8,
      HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 200, DRAIN_CYCLES => 64
    )
    port map (
      ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
      run => run, restart => restart, primed => primed,
      app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
      app_rdy => app_rdy, app_rd_data => app_rd_data,
      app_rd_data_valid => app_rd_data_valid,
      line_rd_en => line_rd_en, line_dout => line_dout, line_empty => line_empty,
      dbg_retry_count => dbg_retry_count, dbg_hb_count => dbg_hb_count
    );

  mig : entity work.mig_read_model
    generic map (ADDR_WIDTH => AW, ADDR_INC => 8, READ_LATENCY => 24,
                 DROP_EVERY => 50, STALL_MASK => 0)  -- inject lost commands to exercise retry
    port map (
      ui_clk => ui_clk, ui_rst => ui_rst,
      app_addr => app_addr, app_cmd => app_cmd, app_en => app_en,
      app_rdy => app_rdy, app_rd_data => app_rd_data,
      app_rd_data_valid => app_rd_data_valid
    );

  -- combinational Standard-FIFO read strobe: pop while in C_REQ and not empty
  line_rd_en <= '1' when (consume_en = '1' and cstate = C_REQ and line_empty = '0') else '0';

  -- consumer FSM on seq_clk
  consumer : process (seq_clk)
  begin
    if rising_edge(seq_clk) then
      if reset_expect = '1' then
        expected <= 0;
        cstate   <= C_WAIT;
        dwell_ctr <= dwell_cycles;
      elsif consume_en = '1' then
        case cstate is
          when C_WAIT =>
            if dwell_ctr = 0 then
              cstate <= C_REQ;
            else
              dwell_ctr <= dwell_ctr - 1;
            end if;
          when C_REQ =>
            if line_empty = '0' then
              cstate <= C_CAP;             -- rd_en fired this cycle (combinational)
            else
              starv <= starv + 1;          -- wanted a line but FIFO empty
            end if;
          when others =>  -- C_CAP: line_dout is valid this cycle
            if unsigned(line_dout) /= to_unsigned(expected, 64) then
              errors <= errors + 1;
              report "ORDER ERROR: expected line " & integer'image(expected) &
                     " got " & integer'image(to_integer(unsigned(line_dout)))
                     severity error;
            end if;
            expected     <= expected + 1;
            lines_popped <= lines_popped + 1;
            dwell_ctr    <= dwell_cycles;
            cstate       <= C_WAIT;
        end case;
      end if;
    end if;
  end process;

  -- stimulus / scoreboard
  stim : process
    -- wait until `lines_popped` has advanced by n (relative), with a watchdog
    procedure consume_n (n : integer) is
      variable target : integer;
      variable guard  : integer := 0;
    begin
      target := lines_popped + n;
      while lines_popped < target loop
        wait until rising_edge(seq_clk);
        guard := guard + 1;
        assert guard < 2000000
          report "WATCHDOG: consumer stalled (starvation/hang)" severity failure;
      end loop;
    end procedure;
  begin
    -- reset
    ui_rst <= '1'; run <= '0'; consume_en <= '0';
    for i in 0 to 9 loop wait until rising_edge(ui_clk); end loop;
    ui_rst <= '0';
    wait until rising_edge(ui_clk);

    -- start streaming, wait for the FIFO to prime
    run <= '1';
    for i in 0 to 5000 loop
      wait until rising_edge(ui_clk);
      exit when primed = '1';
    end loop;
    assert primed = '1' report "FIFO never primed" severity failure;
    report "primed OK after fill";

    -- Phase 1: normal streaming at a representative dwell, 300 lines
    dwell_cycles <= 30;
    consume_en   <= '1';
    consume_n(300);
    report "Phase 1 done: popped=" & integer'image(lines_popped) &
           " errors=" & integer'image(errors) &
           " starv=" & integer'image(starv);
    assert errors = 0 report "Phase 1: order errors" severity failure;
    assert starv  = 0 report "Phase 1: starvation at moderate rate" severity failure;

    -- Phase 2: long dwell -- stop consuming so the FIFO fills and the streamer
    -- goes idle; the keep-warm heartbeat must start firing. Then resume and
    -- confirm the stream continues IN ORDER (the throwaway heartbeat reads must
    -- not advance rd_addr or push into the FIFO).
    consume_en <= '0';
    for i in 0 to 8000 loop wait until rising_edge(ui_clk); end loop;  -- ~98 us dwell
    report "Phase 2 (long dwell): heartbeats=" &
           integer'image(to_integer(unsigned(dbg_hb_count))) &
           " retries=" & integer'image(to_integer(unsigned(dbg_retry_count)));
    assert unsigned(dbg_hb_count) > 0
      report "Phase 2: heartbeat never fired during a full-FIFO idle" severity failure;
    consume_en <= '1';
    consume_n(100);   -- expected continues from 300
    report "Phase 2 resume done: popped=" & integer'image(lines_popped) &
           " errors=" & integer'image(errors) & " starv=" & integer'image(starv);
    assert errors = 0 report "Phase 2: order broken after heartbeats (stream corrupted)" severity failure;

    -- Phase 3: loop-back -- restart rewinds the stream to line 0
    consume_en <= '0';
    wait until rising_edge(seq_clk);
    reset_expect <= '1'; wait until rising_edge(seq_clk); reset_expect <= '0';
    -- pulse restart in the ui_clk domain
    wait until rising_edge(ui_clk); restart <= '1';
    wait until rising_edge(ui_clk); restart <= '0';
    -- wait for re-prime
    for i in 0 to 5000 loop
      wait until rising_edge(ui_clk);
      exit when primed = '1';
    end loop;
    assert primed = '1' report "FIFO never re-primed after restart" severity failure;
    consume_en <= '1';
    consume_n(100);
    report "Phase 3 done (loop-back): popped-since-restart reached, errors=" &
           integer'image(errors) & " starv=" & integer'image(starv);
    assert errors = 0 report "Phase 3: order errors after restart (rewind failed)" severity failure;

    -- the MIG model dropped every 50th command; the streamer must have
    -- recovered each via the lost-command retry (with all data still in order).
    assert unsigned(dbg_retry_count) > 0
      report "lost-command retry path never exercised" severity failure;

    report "ALL TESTS PASSED  (retries=" & integer'image(to_integer(unsigned(dbg_retry_count))) &
           " heartbeats=" & integer'image(to_integer(unsigned(dbg_hb_count))) & ")";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
