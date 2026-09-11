-------------------------------------------------------------------------------
-- tb_pmt_timetagger  (Phase 5 / M4-PMT bring-up)
--
-- Wires the synthetic PMT source (pmt_sim) into the timetagger and checks the
-- 32-bit timestamps it pushes toward fifo_photon (BTPipeOut 0xA0). With the
-- source emitting one pulse every PERIOD cycles, consecutive recorded
-- timestamps must differ by exactly PERIOD (a photon's arrival time is its tick
-- count, so the spacing IS the source period). Then it drops record_en and
-- confirms no further timestamps are recorded while the detection window is
-- closed.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_pmt_timetagger is
end entity;

architecture tb of tb_pmt_timetagger is
  constant PERIOD : natural := 40;      -- pmt_sim: a pulse every 40 clk cycles
  constant NTAGS  : natural := 10;      -- collect this many, then check spacing

  signal clk       : std_logic := '0';
  signal reset     : std_logic := '1';
  signal sim_en    : std_logic := '0';
  signal record_en : std_logic := '0';
  signal pmt       : std_logic;
  signal wr_en     : std_logic;
  signal din       : std_logic_vector(31 downto 0);

  signal period_v  : std_logic_vector(31 downto 0) := std_logic_vector(to_unsigned(PERIOD, 32));

  -- monitor
  signal tags      : integer := 0;
  signal prev_ts   : integer := -1;
  signal errors    : integer := 0;
  signal sim_done  : boolean := false;
begin

  clk <= not clk after 2.5 ns when not sim_done else '0';   -- ~200 MHz (clk_200)

  src : entity work.pmt_sim
    generic map (PERIOD_W => 32)
    port map (clk => clk, reset => reset, enable => sim_en,
              period => period_v, pulse => pmt);

  dut : entity work.pmt_timetagger
    generic map (TS_W => 32)
    port map (clk => clk, reset => reset, record_en => record_en,
              pmt_in => pmt, fifo_full => '0',
              fifo_wr_en => wr_en, fifo_din => din);

  -- monitor: each recorded timestamp must be PERIOD ticks after the previous
  monitor : process (clk)
    variable ts : integer;
  begin
    if rising_edge(clk) then
      if wr_en = '1' then
        ts := to_integer(unsigned(din));
        report "  tag " & integer'image(tags) & " @ tick " & integer'image(ts);
        if prev_ts >= 0 then                       -- have a previous tag to diff
          if (ts - prev_ts) /= PERIOD then
            errors <= errors + 1;
            report "tag " & integer'image(tags) & " spacing = " &
                   integer'image(ts - prev_ts) & " (expected " &
                   integer'image(PERIOD) & ")" severity error;
          end if;
        end if;
        prev_ts <= ts;
        tags    <= tags + 1;
      end if;
      -- no timestamps may be recorded while the window is closed
      if wr_en = '1' and record_en = '0' then
        errors <= errors + 1;
        report "timestamp recorded while record_en = 0" severity error;
      end if;
    end if;
  end process;

  stim : process
    variable tags_at_close : integer;
  begin
    -- reset both blocks
    reset <= '1'; sim_en <= '0'; record_en <= '0';
    for i in 0 to 9 loop wait until rising_edge(clk); end loop;
    reset <= '0';

    -- open the detection window; source + recording on
    sim_en <= '1'; record_en <= '1';
    for i in 0 to NTAGS*PERIOD + 200 loop
      wait until rising_edge(clk);
      exit when tags >= NTAGS;
    end loop;
    assert tags >= NTAGS
      report "did not record " & integer'image(NTAGS) & " timestamps in time" severity failure;

    -- close the window; confirm recording stops (source still running)
    record_en <= '0';
    tags_at_close := tags;
    for i in 0 to 4*PERIOD loop wait until rising_edge(clk); end loop;
    assert tags = tags_at_close
      report "recorded " & integer'image(tags - tags_at_close) &
             " timestamp(s) after the window closed" severity failure;

    assert errors = 0
      report "timetagger mismatch: " & integer'image(errors) & " error(s)" severity failure;
    report "ALL TESTS PASSED: pmt_timetagger records photon times spaced " &
           integer'image(PERIOD) & " ticks apart, window gating clean";
    sim_done <= true;
    wait for 100 ns;
    finish;
  end process;

end architecture;
