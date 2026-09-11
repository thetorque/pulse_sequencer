-------------------------------------------------------------------------------
-- pmt_timetagger  (Phase 5 / M4-PMT: time-resolved photon recording)
--
-- Records the ARRIVAL TIME of each photon into fifo_photon (BTPipeOut 0xA0) --
-- the time-resolved counterpart of pmt_counter's per-window totals. A
-- free-running time counter ticks every clk cycle; while record_en is high
-- (the detection window), each rising edge on the synchronized PMT input
-- pushes the current time-counter value into the FIFO. The host reads the
-- stream of 32-bit timestamps over 0xA0 and differences them for inter-photon
-- intervals.
--
-- Runs on clk_200 (fifo_photon's wr_clk = the reserved "PMT oversampling"
-- clock), so 1 timestamp tick = 5 ns -- finer than the legacy 10 ns
-- timeResolvedResolution. The input is treated as fully async (a real detector,
-- or the synthetic pmt_sim on clk_100) and passed through a 2-FF synchronizer
-- before edge detection, so it is safe to feed from any source/clock.
--
-- record_en gates recording: in the integrated design it is driven either by a
-- control bit (bring-up) or by a sequencer channel bit (the legacy
-- master_logic(17) "TimeResolvedCount"), so a pulse program can open/close the
-- detection window. Timestamps are ABSOLUTE ticks since the last reset.
-- A photon arriving while the FIFO is full is dropped (no wr_en); the FIFO is
-- 32768 deep, ample for a detection window.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pmt_timetagger is
  generic (
    TS_W : natural := 32
  );
  port (
    clk        : in  std_logic;                            -- clk_200 (5 ns/tick)
    reset      : in  std_logic;                            -- async, active high; clears the time counter
    record_en  : in  std_logic;                            -- 1 = record photon timestamps (detection window)
    pmt_in     : in  std_logic;                            -- raw photon signal (async)
    fifo_full  : in  std_logic;                            -- skip the push if the FIFO is full
    fifo_wr_en : out std_logic;                            -- 1-cycle write strobe per recorded photon
    fifo_din   : out std_logic_vector(TS_W-1 downto 0)     -- timestamp: ticks since reset
  );
end entity;

architecture rtl of pmt_timetagger is
  signal sync0, sync1, sync2 : std_logic := '0';           -- 2-FF sync (+1 for edge)
  signal time_ctr : unsigned(TS_W-1 downto 0) := (others => '0');
begin
  process (clk, reset)
  begin
    if reset = '1' then
      sync0 <= '0'; sync1 <= '0'; sync2 <= '0';
      time_ctr   <= (others => '0');
      fifo_wr_en <= '0';
      fifo_din   <= (others => '0');
    elsif rising_edge(clk) then
      fifo_wr_en <= '0';                     -- default single-cycle strobe

      -- synchronize the async input; edge = rising on the synced signal
      sync0 <= pmt_in;
      sync1 <= sync0;
      sync2 <= sync1;

      time_ctr <= time_ctr + 1;              -- free-running 5 ns time base

      -- record this photon's arrival time (the pre-increment time_ctr = now)
      if record_en = '1' and sync1 = '1' and sync2 = '0' and fifo_full = '0' then
        fifo_din   <= std_logic_vector(time_ctr);
        fifo_wr_en <= '1';
      end if;
    end if;
  end process;
end architecture;
