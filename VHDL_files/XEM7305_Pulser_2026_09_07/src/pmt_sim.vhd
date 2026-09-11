-------------------------------------------------------------------------------
-- pmt_sim  (Phase 5 / M4-PMT bring-up)
--
-- Synthetic PMT pulse source: an on-FPGA stand-in for the real PMT_IN signal so
-- the photon-counting datapath (edge detect -> gated counter -> normal_pmt_fifo,
-- and later the time-tagger) can be brought up and verified WITHOUT wiring a
-- physical detector to an input pin. It drops in behind a mux
-- (pmt_in <= sim_pulse when sim_en else real_pin), the same dual-path trick the
-- DDR3 sequencer uses (ep00wire(5)), so the real detector wires in later without
-- disturbing the datapath.
--
-- DETERMINISTIC mode (this version): emits a single-cycle-high pulse once every
-- `period` clk cycles, i.e. an exact, known event rate = f_clk / period. That
-- lets the host verify counts against rate*gate EXACTLY (inject 1 MHz for a
-- 100 ms gate -> expect precisely 100000 counts), a self-checking test with no
-- bench instrument. A pseudo-random (LFSR-gated) mode for Poisson-like realism
-- can be added later behind the same interface; the counter downstream only
-- sees rising edges either way.
--
-- period is in clk cycles and must be >= 1 (period=1 -> a pulse every cycle).
-- Exactly one rising edge per `period` cycles means any window of length m*period
-- captures exactly m edges, independent of phase -- the property the bring-up
-- testbench and the host count-check rely on.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pmt_sim is
  generic (
    PERIOD_W : natural := 32
  );
  port (
    clk    : in  std_logic;
    reset  : in  std_logic;                                -- async, active high
    enable : in  std_logic;                                -- 1 = generate pulses
    period : in  std_logic_vector(PERIOD_W-1 downto 0);    -- clk cycles between pulses (>=1)
    pulse  : out std_logic                                 -- 1-cycle-high per event
  );
end entity;

architecture rtl of pmt_sim is
  signal cnt : unsigned(PERIOD_W-1 downto 0) := (others => '0');
begin
  process (clk, reset)
  begin
    if reset = '1' then
      cnt   <= (others => '0');
      pulse <= '0';
    elsif rising_edge(clk) then
      pulse <= '0';                       -- default: single-cycle strobe
      if enable = '1' then
        -- pulse when the running count reaches period-1, then wrap. Using
        -- (cnt + 1 >= period) also makes period=1 emit every cycle and never
        -- stalls if period is momentarily below cnt after a period change.
        if (cnt + 1) >= unsigned(period) then
          cnt   <= (others => '0');
          pulse <= '1';
        else
          cnt <= cnt + 1;
        end if;
      end if;
    end if;
  end process;
end architecture;
