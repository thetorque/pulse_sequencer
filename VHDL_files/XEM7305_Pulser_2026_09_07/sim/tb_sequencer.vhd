-------------------------------------------------------------------------------
-- tb_sequencer  (Phase 6c milestone 3 -- combined streamer + sequencer)
--
-- Wires ddr3_line_streamer (fed by a program-backed MIG model) to
-- pulse_sequencer and checks that the emitted master_logic waveform matches
-- the program in mig_prog_model:
--   0x1 (3 ticks) -> 0x2 (5 ticks) -> 0x4 (2 ticks) -> 0 (done).
-- One tick = 4 seq_clk cycles, so the 0x2 segment must last 20 cycles and the
-- 0x4 segment 8 cycles. Proves the FIFO-fed sequencer reproduces the exact
-- program timing end to end (DDR3 read -> FIFO CDC -> sequencer FSM).
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_sequencer is
end entity;

architecture tb of tb_sequencer is
  constant AW : natural := 29;

  signal ui_clk  : std_logic := '0';
  signal seq_clk : std_logic := '0';   -- = clk_100
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

  -- sequencer
  signal seq_reset    : std_logic := '1';
  signal seq_start    : std_logic := '0';
  signal seq_infinite : std_logic := '0';
  signal master_logic : std_logic_vector(31 downto 0);
  signal seq_done     : std_logic;

  -- monitor
  signal prev_master : std_logic_vector(31 downto 0) := (others => '0');
  signal held        : integer := 0;
  signal errors      : integer := 0;
  signal sim_done    : boolean := false;
begin

  ui_clk  <= not ui_clk  after 6.154 ns when not sim_done else '0';
  seq_clk <= not seq_clk after 5.000 ns when not sim_done else '0';

  streamer : entity work.ddr3_line_streamer
    generic map (ADDR_WIDTH => AW, BASE_ADDR => 0, ADDR_INC => 8,
                 SCRATCH_XOR_BIT => 25, PRIME_BEATS => 4,
                 HEARTBEAT_CYCLES => 40, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
    port map (ui_clk => ui_clk, ui_rst => ui_rst, seq_clk => seq_clk,
              run => run, restart => restart, primed => primed,
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
              infinite => seq_infinite, prog_ready => primed,
              line_trig_en => '0', line_trig_pulse => '0', loop_limit => (others => '0'),
              line_dout => line_dout, line_empty => line_empty, line_rd_en => line_rd_en,
              restart => restart, master_logic => master_logic,
              seq_count_out => open, seq_done => seq_done);

  -- monitor: report each master_logic segment and check the value sequence +
  -- the two clean mid-sequence dwell durations.
  monitor : process (seq_clk)
    variable seg : integer := 0;
  begin
    if rising_edge(seq_clk) then
      if master_logic /= prev_master then
        report "  segment " & integer'image(seg) & ": value 0x" &
               integer'image(to_integer(unsigned(prev_master))) & " held " &
               integer'image(held) & " cycles -> next 0x" &
               integer'image(to_integer(unsigned(master_logic)));
        case seg is
          when 1 =>   -- 0x1 -> 0x2
            if not (prev_master = x"00000001" and master_logic = x"00000002") then
              errors <= errors + 1; report "seg1 value wrong" severity error;
            end if;
          when 2 =>   -- 0x2 -> 0x4; spacing = held+1 = 5 ticks = 20 cycles
            if not (prev_master = x"00000002" and master_logic = x"00000004") then
              errors <= errors + 1; report "seg2 value wrong" severity error;
            end if;
            if (held + 1) /= 20 then errors <= errors + 1;
              report "0x2 dwell = " & integer'image(held+1) & " cycles (expected 20)" severity error;
            end if;
          when 3 =>   -- 0x4 -> 0x0; spacing = held+1 = 2 ticks = 8 cycles
            if not (prev_master = x"00000004" and master_logic = x"00000000") then
              errors <= errors + 1; report "seg3 value wrong" severity error;
            end if;
            if (held + 1) /= 8 then errors <= errors + 1;
              report "0x4 dwell = " & integer'image(held+1) & " cycles (expected 8)" severity error;
            end if;
          when others => null;
        end case;
        seg := seg + 1;
        held <= 0;
        prev_master <= master_logic;
      else
        held <= held + 1;
      end if;
    end if;
  end process;

  stim : process
  begin
    -- reset streamer + sequencer
    ui_rst <= '1'; seq_reset <= '1'; run <= '0'; seq_start <= '0'; seq_infinite <= '0';
    for i in 0 to 9 loop wait until rising_edge(ui_clk); end loop;
    ui_rst <= '0';
    run <= '1';                                   -- start the streamer
    for i in 0 to 5000 loop wait until rising_edge(ui_clk); exit when primed = '1'; end loop;
    assert primed = '1' report "streamer never primed" severity failure;

    -- release + start the sequencer
    wait until rising_edge(seq_clk);
    seq_reset <= '0';
    wait until rising_edge(seq_clk);
    seq_start <= '1';

    -- wait for the one-shot to finish
    for i in 0 to 20000 loop
      wait until rising_edge(seq_clk);
      exit when seq_done = '1';
    end loop;
    assert seq_done = '1' report "sequencer never reached DONE" severity failure;
    -- let the final segment report
    for i in 0 to 10 loop wait until rising_edge(seq_clk); end loop;

    assert errors = 0
      report "waveform mismatch: " & integer'image(errors) & " error(s)" severity failure;
    report "ALL TESTS PASSED: FIFO-fed sequencer reproduced the program waveform";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
