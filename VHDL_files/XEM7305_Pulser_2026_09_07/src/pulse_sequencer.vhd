-------------------------------------------------------------------------------
-- pulse_sequencer  (Phase 6c milestone 3)
--
-- The pulse-sequence FSM, adapted to read program lines from a FIFO (fed by
-- ddr3_line_streamer) instead of random-addressing pulser_ram. The timing
-- semantics are preserved exactly from photon.vhd's Phase 5a FSM:
--   * line = time(61:32) & channel(31:0); channel drives master_logic.
--   * one tick = 4 clk cycles (40 ns @ clk_100); time_count advances per tick,
--     a line's channel is held for the NEXT line's `time` ticks.
--   * terminator = a line whose time field is 0. One-shot -> outputs 0 and
--     stops; infinite -> pulses `restart` (rewinds the streamer) and reloads.
--
-- Because a Standard FIFO read has a cycle of latency, a 1-deep prefetch
-- register (pf) is kept topped up during each dwell, so transitions are
-- zero-latency (the sequencer's original pulser_ram access was zero-latency
-- via address look-ahead). If the FIFO underruns at a transition the FSM
-- stalls (holds the current state) rather than emitting garbage.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pulse_sequencer is
  port (
    clk          : in  std_logic;                       -- clk_100
    reset        : in  std_logic;                       -- async, active high (pulser_counter_reset)
    start        : in  std_logic;                       -- pulser_start_bit
    infinite     : in  std_logic;                       -- pulser_infinite_loop
    prog_ready   : in  std_logic;                       -- streamer primed (FIFO has data)
    -- line-trigger gate (Phase 5b): when line_trig_en='1', wait for a
    -- line_trig_pulse before starting each run (and each loop iteration).
    line_trig_en    : in  std_logic;
    line_trig_pulse : in  std_logic;
    -- infinite-loop iteration limit: 0 = unlimited, else stop after N loops.
    loop_limit      : in  std_logic_vector(15 downto 0);
    -- program line source (streamer FIFO read side, Standard FIFO)
    line_dout    : in  std_logic_vector(63 downto 0);
    line_empty   : in  std_logic;
    line_rd_en   : out std_logic;
    -- to streamer
    restart      : out std_logic;                       -- 1-cycle pulse on loop-back
    -- outputs
    master_logic : out std_logic_vector(31 downto 0);
    seq_count_out: out std_logic_vector(15 downto 0);   -- completed loop iterations
    seq_done     : out std_logic;
    -- integrity: total lines popped from the FIFO this run (host compares to the
    -- program length -- a dropped/duplicated line from ANY cause changes it).
    line_count   : out std_logic_vector(31 downto 0)
  );
end entity;

architecture rtl of pulse_sequencer is
  type st_t is (S_IDLE, S_TRIGWAIT, S_P0REQ, S_P0CAP, S_P1REQ, S_P1CAP,
                S_RUN, S_WAITPRIME, S_DONE);
  signal st        : st_t := S_IDLE;

  signal d1, d2    : std_logic_vector(63 downto 0) := (others => '0');
  signal pf_line   : std_logic_vector(63 downto 0) := (others => '0');
  signal pf_valid  : std_logic := '0';
  signal pop_phase : integer range 0 to 1 := 0;

  signal count1    : integer range 0 to 3 := 0;
  signal time_count: integer := 0;
  signal time_stamp: integer := 0;
  signal seq_count : integer range 0 to 65535 := 0;

  signal rd_en_i   : std_logic;                          -- internal copy of line_rd_en (readable)
  signal line_cnt  : unsigned(31 downto 0) := (others => '0');  -- lines popped this run

  function tfield(l : std_logic_vector(63 downto 0)) return integer is
  begin
    return to_integer(unsigned(l(61 downto 32)));
  end function;
begin

  -- combinational Standard-FIFO read strobe: one cycle in each REQ/prefetch
  rd_en_i <= '1' when line_empty = '0' and
                  ( st = S_P0REQ or st = S_P1REQ or
                    (st = S_RUN and pop_phase = 0 and pf_valid = '0') )
                else '0';
  line_rd_en <= rd_en_i;

  seq_count_out <= std_logic_vector(to_unsigned(seq_count, 16));
  line_count    <= std_logic_vector(line_cnt);

  process (clk, reset)
  begin
    if reset = '1' then
      st           <= S_IDLE;
      master_logic <= (others => '0');
      seq_done     <= '0';
      restart      <= '0';
      pf_valid     <= '0';
      pop_phase    <= 0;
      count1       <= 0;
      time_count   <= 0;
      time_stamp   <= 0;
      seq_count    <= 0;
      line_cnt     <= (others => '0');
    elsif rising_edge(clk) then
      restart <= '0';   -- default single-cycle strobe

      -- integrity counter: one increment per line actually popped from the FIFO
      if rd_en_i = '1' then line_cnt <= line_cnt + 1; end if;

      case st is
        when S_IDLE =>
          seq_done  <= '0';
          seq_count <= 0;
          if start = '1' and prog_ready = '1' then
            st <= S_TRIGWAIT;
          end if;

        -- line-trigger gate: wait for a trigger pulse when enabled (checked at
        -- the start of the run and again on every loop iteration).
        when S_TRIGWAIT =>
          if line_trig_en = '0' or line_trig_pulse = '1' then
            st <= S_P0REQ;
          end if;

        -- prime: load line 0 (current) and line 1 (next)
        when S_P0REQ =>
          if line_empty = '0' then st <= S_P0CAP; end if;
        when S_P0CAP =>
          d1           <= line_dout;
          master_logic <= line_dout(31 downto 0);
          st           <= S_P1REQ;
        when S_P1REQ =>
          if line_empty = '0' then st <= S_P1CAP; end if;
        when S_P1CAP =>
          d2         <= line_dout;
          time_stamp <= tfield(line_dout);
          count1     <= 0;
          time_count <= 0;
          pf_valid   <= '0';
          pop_phase  <= 0;
          st         <= S_RUN;

        when S_RUN =>
          -- prefetch engine (runs in parallel with the tick)
          if pop_phase = 0 then
            if pf_valid = '0' and line_empty = '0' then
              pop_phase <= 1;                 -- rd_en asserted (combinational) this cycle
            end if;
          else
            pf_line   <= line_dout;
            pf_valid  <= '1';
            pop_phase <= 0;
          end if;

          -- tick engine (40 ns tick = 4 clk). time_count free-runs (never reset
          -- per line); each line's `time` is the ABSOLUTE tick of its state
          -- change. Increment-then-compare, matching photon.vhd exactly.
          if count1 = 3 then
            count1 <= 0;
            if (time_count + 1) = time_stamp then
              if pf_valid = '1' then          -- transition (next line ready)
                time_count <= time_count + 1; -- commit the tick
                d1         <= d2;
                d2         <= pf_line;
                pf_valid   <= '0';            -- consuming pf triggers the next prefetch
                if tfield(pf_line) = 0 then   -- terminator reached
                  if infinite = '1' and
                     ( unsigned(loop_limit) = 0 or
                       (seq_count + 1) /= to_integer(unsigned(loop_limit)) ) then
                    seq_count    <= seq_count + 1;
                    restart      <= '1';                    -- rewind the streamer
                    master_logic <= d2(31 downto 0);        -- hold last real state
                    st           <= S_WAITPRIME;
                  else
                    -- one-shot, or infinite loop reached its iteration limit
                    if infinite = '1' then seq_count <= seq_count + 1; end if;
                    master_logic <= (others => '0');
                    st           <= S_DONE;
                  end if;
                else
                  time_stamp   <= tfield(pf_line);
                  master_logic <= d2(31 downto 0);          -- new current channel
                end if;
              end if;
              -- pf not ready: stall (do NOT commit the tick, retry next tick)
            else
              time_count <= time_count + 1;
            end if;
          else
            count1 <= count1 + 1;
          end if;

        when S_WAITPRIME =>
          -- after a loop restart, wait for the streamer to re-prime, then
          -- re-arm the line trigger before reloading (matches the original FSM,
          -- which re-waits the trigger on every loop iteration).
          if prog_ready = '1' then
            st <= S_TRIGWAIT;
          end if;

        when others =>  -- S_DONE
          seq_done <= '1';
      end case;
    end if;
  end process;

end architecture;
