-------------------------------------------------------------------------------
-- pmt_diff_counter  (Phase 5 / M4-PMT: differential / sequence-gated counting)
--
-- Differential-mode photon counting: instead of the free-running collection
-- gate of pmt_counter (normal mode), the count window is defined by the running
-- pulse SEQUENCE. Each rising edge of `trigger` (the sequence's DiffCountTrigger
-- channel) closes the current window -- it snapshots the photons accumulated
-- since the previous trigger, pushes one 32-bit word into normal_pmt_fifo, and
-- resets the accumulator for the next window.
--
-- The pushed word carries the repump (866) state in bit 31 so the host can do
-- differential detection (count with 866 on vs off, then subtract):
--   bits[30:0] = photon count for the window
--   bit  31    = '0' when status_in (866) is '1' (ON), else '1' (OFF)
-- i.e. a word >= 2^31 means "866 was OFF" -- exactly the legacy host decode
-- (pulser_ok.infoFromBuf: count >= 2^31 -> 'OFF'). Matches the 2015 photon.vhd
-- (normal_pmt_count_trigger / master_logic(16) / master_logic(0)).
--
-- The PMT input is synchronized (2-FF) before edge detection, so it is safe to
-- feed from any source. `trigger` and `status_in` come from the sequencer's
-- master_logic (clk_100 domain, same as this module) -- no CDC. A window whose
-- count arrives while the FIFO is full is dropped (no wr_en).
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pmt_diff_counter is
  port (
    clk        : in  std_logic;                            -- clk_100
    reset      : in  std_logic;                            -- async, active high
    trigger    : in  std_logic;                            -- DiffCountTrigger (master_logic(16)); rising edge closes a window
    status_in  : in  std_logic;                            -- 866 state (master_logic(0)); ON = '1'
    pmt_in     : in  std_logic;                            -- raw photon signal (async)
    fifo_full  : in  std_logic;                            -- skip the push if the FIFO is full
    fifo_wr_en : out std_logic;                            -- 1-cycle write strobe per closed window
    fifo_din   : out std_logic_vector(31 downto 0)         -- bit31 = 866-off status, [30:0] = count
  );
end entity;

architecture rtl of pmt_diff_counter is
  signal sync0, sync1, sync2 : std_logic := '0';           -- 2-FF sync (+1 for edge)
  signal trig_d   : std_logic := '0';                      -- for trigger rising-edge detect
  signal count    : unsigned(30 downto 0) := (others => '0');  -- 31-bit photon accumulator
begin
  process (clk, reset)
    variable edge     : std_logic;
    variable trig_rise: std_logic;
    variable cnt_v    : unsigned(30 downto 0);
  begin
    if reset = '1' then
      sync0 <= '0'; sync1 <= '0'; sync2 <= '0';
      trig_d     <= '0';
      count      <= (others => '0');
      fifo_wr_en <= '0';
      fifo_din   <= (others => '0');
    elsif rising_edge(clk) then
      fifo_wr_en <= '0';                 -- default: single-cycle strobe

      -- synchronize the async photon input; edge = rising on the synced signal
      sync0 <= pmt_in;
      sync1 <= sync0;
      sync2 <= sync1;
      edge := sync1 and not sync2;

      -- rising edge of the sequence's count trigger closes a window
      trig_rise := trigger and not trig_d;
      trig_d    <= trigger;

      -- this cycle's photon folded into the running total first
      if edge = '1' then
        cnt_v := count + 1;
      else
        cnt_v := count;
      end if;

      if trig_rise = '1' then
        -- close the window: publish count + 866 status, restart the accumulator
        fifo_din(30 downto 0) <= std_logic_vector(cnt_v);
        if status_in = '1' then         -- 866 ON  -> bit31 = '0'
          fifo_din(31) <= '0';
        else                            -- 866 OFF -> bit31 = '1' (word >= 2^31)
          fifo_din(31) <= '1';
        end if;
        if fifo_full = '0' then
          fifo_wr_en <= '1';
        end if;
        count <= (others => '0');
      else
        count <= cnt_v;
      end if;
    end if;
  end process;
end architecture;
