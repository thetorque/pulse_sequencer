-------------------------------------------------------------------------------
-- tb_pmt_diff_counter  (Phase 5 / M4-PMT bring-up)
--
-- Drives the differential counter with a synthetic photon source (pmt_sim), a
-- synthetic sequence trigger (standing in for master_logic(16), a rising edge
-- every TRIG cycles), and a status input (866). Each closed window must report
-- exactly TRIG/PERIOD photons in bits[30:0], and bit 31 must be the inverted
-- 866 state ('0' when 866 ON, '1' when OFF). Checks the count under both status
-- values, gating the status check to windows where 866 has settled (so the
-- transition window is not checked). The startup windows (first trigger fires
-- at t=0 with an empty accumulator) are skipped.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_pmt_diff_counter is
end entity;

architecture tb of tb_pmt_diff_counter is
  constant PERIOD : natural := 50;      -- pmt_sim: a photon every 50 cycles
  constant TRIG   : natural := 1000;    -- sequence trigger: a rising edge every 1000 cycles
  constant EXPECT : natural := TRIG / PERIOD;   -- = 20 photons per window
  constant SKIP   : natural := 2;       -- skip startup windows

  signal clk       : std_logic := '0';
  signal reset     : std_logic := '1';
  signal sim_en    : std_logic := '0';
  signal status    : std_logic := '1';   -- 866: '1' = ON
  signal status_stable : std_logic := '0';
  signal pmt       : std_logic;
  signal trigger   : std_logic := '0';
  signal wr_en     : std_logic;
  signal din       : std_logic_vector(31 downto 0);

  signal period_v  : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(PERIOD, 32));

  -- monitor
  signal windows   : integer := 0;
  signal errors    : integer := 0;
  signal sim_done  : boolean := false;
begin

  clk <= not clk after 5 ns when not sim_done else '0';

  src : entity work.pmt_sim
    generic map (PERIOD_W => 32)
    port map (clk => clk, reset => reset, enable => sim_en,
              period => period_v, pulse => pmt);

  dut : entity work.pmt_diff_counter
    port map (clk => clk, reset => reset, trigger => trigger,
              status_in => status, pmt_in => pmt, fifo_full => '0',
              fifo_wr_en => wr_en, fifo_din => din);

  -- synthetic sequence trigger: rising edge every TRIG cycles (high first half)
  trig_gen : process (clk)
    variable c : integer range 0 to TRIG-1 := 0;
  begin
    if rising_edge(clk) then
      if reset = '1' then
        c := 0; trigger <= '1';
      else
        if c = TRIG-1 then c := 0; else c := c + 1; end if;
        if c < TRIG/2 then trigger <= '1'; else trigger <= '0'; end if;
      end if;
    end if;
  end process;

  -- monitor: check each closed window's count, and the 866 status bit once settled
  monitor : process (clk)
    variable cnt  : integer;
    variable stat : std_logic;
  begin
    if rising_edge(clk) then
      if wr_en = '1' then
        cnt  := to_integer(unsigned(din(30 downto 0)));
        stat := din(31);
        report "  window " & integer'image(windows) & ": count=" &
               integer'image(cnt) & " status_bit=" & std_logic'image(stat);
        if windows >= SKIP then
          if cnt /= EXPECT then
            errors <= errors + 1;
            report "window " & integer'image(windows) & " count=" &
                   integer'image(cnt) & " (expected " & integer'image(EXPECT) & ")" severity error;
          end if;
          if status_stable = '1' then
            -- bit31 = NOT 866: '0' when status='1', '1' when status='0'
            if stat /= (not status) then
              errors <= errors + 1;
              report "window " & integer'image(windows) & " status_bit wrong for 866=" &
                     std_logic'image(status) severity error;
            end if;
          end if;
        end if;
        windows <= windows + 1;
      end if;
    end if;
  end process;

  stim : process
    variable w : integer;
  begin
    reset <= '1'; sim_en <= '0'; status <= '1'; status_stable <= '0';
    for i in 0 to 9 loop wait until rising_edge(clk); end loop;
    reset <= '0';
    sim_en <= '1';

    -- Phase A: 866 ON (status=1 -> bit31=0). Let it settle, then check.
    for i in 0 to 3*TRIG loop wait until rising_edge(clk); exit when windows >= 3; end loop;
    status_stable <= '1';
    w := windows;
    for i in 0 to 5*TRIG loop wait until rising_edge(clk); exit when windows >= w + 5; end loop;

    -- Phase B: 866 OFF (status=0 -> bit31=1). Drop the check across the change.
    status_stable <= '0';
    status <= '0';
    for i in 0 to 3*TRIG loop wait until rising_edge(clk); exit when windows >= w + 8; end loop;
    status_stable <= '1';
    w := windows;
    for i in 0 to 5*TRIG loop wait until rising_edge(clk); exit when windows >= w + 5; end loop;

    assert windows >= 15 report "too few windows observed" severity failure;
    assert errors = 0
      report "diff counter mismatch: " & integer'image(errors) & " error(s)" severity failure;
    report "ALL TESTS PASSED: pmt_diff_counter counts " & integer'image(EXPECT) &
           "/window, 866 status bit tracks both states";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
