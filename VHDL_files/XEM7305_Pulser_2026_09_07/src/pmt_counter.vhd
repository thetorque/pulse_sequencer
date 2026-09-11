-------------------------------------------------------------------------------
-- pmt_counter  (Phase 5 / M4-PMT bring-up)
--
-- Normal-mode periodic photon counter -- the missing "write side" of
-- normal_pmt_fifo (photon.vhd's read side / BTPipeOut 0xA1 already exists).
-- It synchronizes the raw PMT input, counts rising edges over a fixed
-- collection-time gate of `gate_len` clk cycles, and at each gate close pushes
-- the accumulated count into the FIFO and immediately opens the next gate --
-- the free-running "Normal" counting mode of the legacy pulser (host reads a
-- stream of per-window counts). Differential (sequence-gated) mode and the
-- time-resolved tagger are separate follow-on blocks.
--
-- The input is treated as fully asynchronous (a real detector, or the
-- synthetic pmt_sim on another clock) and passed through a 2-FF synchronizer
-- before edge detection, so it is safe to feed from any source.
--
-- gate_len is in clk cycles and must be >= 1. A window closes when the gate
-- counter has been open for gate_len cycles; the edge arriving on the closing
-- cycle is counted in the window that closes (so back-to-back windows tile the
-- timeline with no missed cycle). With pmt_sim's exact period P and
-- gate_len = m*P, every steady-state window reports exactly m counts.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pmt_counter is
  generic (
    CNT_W  : natural := 32;
    GATE_W : natural := 32
  );
  port (
    clk        : in  std_logic;
    reset      : in  std_logic;                            -- async, active high
    enable     : in  std_logic;                            -- 1 = run periodic gating
    pmt_in     : in  std_logic;                            -- raw photon signal (async)
    gate_len   : in  std_logic_vector(GATE_W-1 downto 0);  -- clk cycles per collection window
    fifo_full  : in  std_logic;                            -- skip the push if the FIFO is full
    fifo_wr_en : out std_logic;                            -- 1-cycle write strobe at gate close
    fifo_din   : out std_logic_vector(CNT_W-1 downto 0);   -- the closing window's count
    sample     : out std_logic                             -- 1-cycle strobe at each gate close
  );
end entity;

architecture rtl of pmt_counter is
  signal sync0, sync1, sync2 : std_logic := '0';           -- 2-FF sync (+1 for edge)
  signal count    : unsigned(CNT_W-1 downto 0)  := (others => '0');
  signal gate_ctr : unsigned(GATE_W-1 downto 0) := (others => '0');
begin
  process (clk, reset)
    variable cnt_v : unsigned(CNT_W-1 downto 0);
  begin
    if reset = '1' then
      sync0 <= '0'; sync1 <= '0'; sync2 <= '0';
      count      <= (others => '0');
      gate_ctr   <= (others => '0');
      fifo_wr_en <= '0';
      fifo_din   <= (others => '0');
      sample     <= '0';
    elsif rising_edge(clk) then
      fifo_wr_en <= '0';                 -- default: single-cycle strobes
      sample     <= '0';

      -- synchronize the async input; edge = rising on the synced signal
      sync0 <= pmt_in;
      sync1 <= sync0;
      sync2 <= sync1;

      if enable = '1' then
        -- fold this cycle's edge into the running total first
        if sync1 = '1' and sync2 = '0' then
          cnt_v := count + 1;
        else
          cnt_v := count;
        end if;

        if (gate_ctr + 1) >= unsigned(gate_len) then
          -- window closes this cycle: publish the count, restart the gate
          fifo_din <= std_logic_vector(cnt_v);
          if fifo_full = '0' then
            fifo_wr_en <= '1';
          end if;
          sample   <= '1';
          count    <= (others => '0');
          gate_ctr <= (others => '0');
        else
          count    <= cnt_v;
          gate_ctr <= gate_ctr + 1;
        end if;
      end if;
    end if;
  end process;
end architecture;
