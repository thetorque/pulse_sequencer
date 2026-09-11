-------------------------------------------------------------------------------
-- tb_pmt_counter  (Phase 5 / M4-PMT bring-up)
--
-- Wires the synthetic PMT source (pmt_sim) into the normal-mode counter
-- (pmt_counter) and checks the per-window counts pushed toward normal_pmt_fifo.
-- With pmt_sim emitting one pulse every PERIOD cycles and a gate of GATE cycles,
-- every steady-state window must report EXACTLY GATE/PERIOD counts. The FIRST
-- window reads one low (the source's first edge is delayed by the counter's
-- 2-FF input synchronizer), so the first couple of windows are skipped before
-- the exact check -- the same startup transient real hardware would show.
--
-- Then it drops `enable` and confirms the counter stops pushing (no stray
-- windows while paused), and re-enables to confirm it resumes.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_pmt_counter is
end entity;

architecture tb of tb_pmt_counter is
  constant PERIOD : natural := 10;      -- pmt_sim: a pulse every 10 clk cycles
  constant GATE   : natural := 1000;    -- counter: 1000-cycle collection window
  constant EXPECT : natural := GATE / PERIOD;   -- = 100 counts per steady window
  constant SKIP   : natural := 2;       -- windows to skip for the startup transient

  signal clk      : std_logic := '0';
  signal reset    : std_logic := '1';
  signal sim_en   : std_logic := '0';
  signal cnt_en   : std_logic := '0';
  signal pmt      : std_logic;
  signal wr_en    : std_logic;
  signal din      : std_logic_vector(31 downto 0);
  signal sample   : std_logic;

  signal period_v : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(PERIOD, 32));
  signal gate_v   : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(GATE, 32));

  -- monitor
  signal windows  : integer := 0;       -- how many gate closes seen
  signal errors   : integer := 0;
  signal sim_done : boolean := false;
begin

  clk <= not clk after 5 ns when not sim_done else '0';

  src : entity work.pmt_sim
    generic map (PERIOD_W => 32)
    port map (clk => clk, reset => reset, enable => sim_en,
              period => period_v, pulse => pmt);

  dut : entity work.pmt_counter
    generic map (CNT_W => 32, GATE_W => 32)
    port map (clk => clk, reset => reset, enable => cnt_en,
              pmt_in => pmt, gate_len => gate_v, fifo_full => '0',
              fifo_wr_en => wr_en, fifo_din => din, sample => sample);

  -- monitor: on each gate close, check the count (after the startup skip)
  monitor : process (clk)
  begin
    if rising_edge(clk) then
      if wr_en = '1' then
        report "  window " & integer'image(windows) & ": count = " &
               integer'image(to_integer(unsigned(din)));
        -- exact check only on the contiguous Phase-A steady windows [SKIP, 8):
        -- window 0 is the reset/sync startup transient, and the window that
        -- spans the later pause is short because pmt_sim keeps emitting while
        -- the counter is disabled (both are physical, not faults).
        if windows >= SKIP and windows < 8 then
          if to_integer(unsigned(din)) /= EXPECT then
            errors <= errors + 1;
            report "window " & integer'image(windows) & " count = " &
                   integer'image(to_integer(unsigned(din))) & " (expected " &
                   integer'image(EXPECT) & ")" severity error;
          end if;
        end if;
        windows <= windows + 1;
      end if;
      -- wr_en must pulse only when the counter is enabled
      if wr_en = '1' and cnt_en = '0' then
        errors <= errors + 1;
        report "wr_en asserted while counter disabled" severity error;
      end if;
    end if;
  end process;

  stim : process
    variable w_at_pause : integer;
  begin
    -- reset both blocks
    reset <= '1'; sim_en <= '0'; cnt_en <= '0';
    for i in 0 to 9 loop wait until rising_edge(clk); end loop;
    reset <= '0';

    -- run: source + counter on. Collect several steady windows. The loop bound
    -- has margin over 8 windows (~80 us) since window 0 is delayed by the
    -- reset/sync startup; it exits early once 8 windows have closed.
    sim_en <= '1'; cnt_en <= '1';
    for i in 0 to 12*GATE loop
      wait until rising_edge(clk);
      exit when windows >= 8;
    end loop;
    assert windows >= 8
      report "did not observe 8 windows in time" severity failure;

    -- pause the counter; confirm no further gate closes for a couple windows
    cnt_en <= '0';
    w_at_pause := windows;
    for i in 0 to 2*GATE loop wait until rising_edge(clk); end loop;
    assert windows = w_at_pause
      report "counter produced windows while paused (" &
             integer'image(windows - w_at_pause) & " extra)" severity failure;

    -- resume; confirm it starts closing windows again
    cnt_en <= '1';
    for i in 0 to 3*GATE loop
      wait until rising_edge(clk);
      exit when windows > w_at_pause + 1;
    end loop;
    assert windows > w_at_pause + 1
      report "counter did not resume after re-enable" severity failure;

    assert errors = 0
      report "PMT counter mismatch: " & integer'image(errors) & " error(s)" severity failure;
    report "ALL TESTS PASSED: pmt_sim -> pmt_counter counts " &
           integer'image(EXPECT) & "/window, pause/resume clean";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
