-------------------------------------------------------------------------------
-- ddr3_line_streamer  (Phase 6c, milestone 1)
--
-- Streams 64-bit pulse-sequence lines out of DDR3 (via the MIG native app
-- interface) into a 128-write / 64-read independent-clocks prefetch FIFO that
-- the sequencer FSM pops from. It reuses the proven Phase 6b read-prefetch
-- handshake (assert app_en only until app_rdy, commit on VALID, bounded
-- lost-command retry) and adds three things the sequencer needs:
--
--   * Autonomous refill: keep the FIFO topped up from a sequential address
--     walk starting at BASE_ADDR (no host command budget).
--   * Keep-warm heartbeat: when the FIFO is full the read engine would go
--     idle; during long pulse dwells that lets the DDR3 controller go "cold"
--     and the first read afterwards can mis-address (the Phase 6b cold-start
--     corner). So while idle it issues a throwaway read to a DIFFERENT bank
--     (BASE_ADDR walk XOR a bank bit) every HEARTBEAT_CYCLES and discards it,
--     keeping the controller warm. NOTE: the heartbeat's EFFECTIVENESS is a
--     silicon-timing property that simulation cannot reproduce -- sim proves
--     the logic (it fires, it is discarded, it does not disturb the stream);
--     hardware proves it keeps the controller warm (as --sacrifice-beat0 did).
--   * Loop-back: a `restart` pulse rewinds the address walk to BASE_ADDR and
--     flushes the FIFO, for the sequencer's infinite-loop mode.
--
-- Clocking: the read engine and MIG run on ui_clk; the sequencer reads the
-- FIFO on seq_clk (clk_100). The prefetch FIFO is the CDC between them.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ddr3_line_streamer is
  generic (
    ADDR_WIDTH       : natural := 29;   -- MIG app_addr width
    BASE_ADDR        : natural := 0;    -- app_addr of program line 0
    ADDR_INC         : natural := 8;    -- app_addr per 128-bit read (one beat = 2 lines)
    SCRATCH_XOR_BIT  : natural := 25;   -- heartbeat target = current addr XOR (1<<bit): a different bank
    PRIME_BEATS      : natural := 8;    -- FIFO beats buffered before `primed` asserts
    HEARTBEAT_CYCLES : natural := 81;   -- ui_clk cycles between warm-up reads when idle (~1 us @ 81.25 MHz)
    RETRY_TIMEOUT    : natural := 2047; -- lost-command timeout, ui_clk cycles (~25 us)
    DRAIN_CYCLES     : natural := 64    -- on restart, discard in-flight responses this long (> read latency)
  );
  port (
    ui_clk            : in  std_logic;
    ui_rst            : in  std_logic;  -- sync, active high (global reset)
    seq_clk           : in  std_logic;  -- sequencer read clock (clk_100)

    -- control (ui_clk domain; synchronise external pulses before driving)
    run               : in  std_logic;  -- level: enable streaming
    restart           : in  std_logic;  -- 1-cycle pulse: rewind to BASE_ADDR + flush FIFO
    primed            : out std_logic;  -- FIFO holds >= PRIME_BEATS beats (ui_clk domain)

    -- MIG native app interface (read only)
    app_addr          : out std_logic_vector(ADDR_WIDTH-1 downto 0);
    app_cmd           : out std_logic_vector(2 downto 0);
    app_en            : out std_logic;
    app_rdy           : in  std_logic;
    app_rd_data       : in  std_logic_vector(127 downto 0);
    app_rd_data_valid : in  std_logic;

    -- line output to the sequencer (Standard FIFO read side, seq_clk domain)
    line_rd_en        : in  std_logic;
    line_dout         : out std_logic_vector(63 downto 0);
    line_empty        : out std_logic;

    -- diagnostics (ui_clk domain, 8-bit wrapping)
    dbg_retry_count   : out std_logic_vector(7 downto 0);
    dbg_hb_count      : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of ddr3_line_streamer is

  -- 128-write / 64-read independent-clocks Standard FIFO. In the real design
  -- this is the Xilinx fifo_generator IP (ddr3_line_fifo); for simulation a
  -- behavioural architecture of the same entity is provided in sim/.
  component fifo_128x4 is
    port (
      rst           : in  std_logic;
      wr_clk        : in  std_logic;
      rd_clk        : in  std_logic;
      din           : in  std_logic_vector(127 downto 0);
      wr_en         : in  std_logic;
      rd_en         : in  std_logic;
      dout          : out std_logic_vector(63 downto 0);
      full          : out std_logic;
      empty         : out std_logic;
      wr_data_count : out std_logic_vector(7 downto 0);  -- write side, in 128-bit beats (0..255; full via 'full' flag)
      rd_data_count : out std_logic_vector(8 downto 0)   -- read side, in 64-bit lines (0..511)
    );
  end component;

  type state_t is (S_IDLE, S_WAIT_RDY, S_WAIT_VALID, S_DRAIN);
  signal state    : state_t := S_IDLE;

  signal rd_addr   : unsigned(ADDR_WIDTH-1 downto 0) := to_unsigned(BASE_ADDR, ADDR_WIDTH);
  signal is_hb     : std_logic := '0';                    -- current handshake is a heartbeat (discard)
  signal wait_ctr  : unsigned(11 downto 0) := (others => '0');
  signal hb_timer  : unsigned(15 downto 0) := (others => '0');
  signal drain_ctr : unsigned(11 downto 0) := (others => '0');

  signal retry_count : unsigned(7 downto 0) := (others => '0');
  signal hb_count    : unsigned(7 downto 0) := (others => '0');

  -- FIFO glue
  signal fifo_rst   : std_logic := '0';
  signal fifo_din   : std_logic_vector(127 downto 0) := (others => '0');
  signal fifo_wr_en : std_logic := '0';
  signal fifo_full  : std_logic;
  signal fifo_wrcnt : std_logic_vector(7 downto 0);

  constant SCRATCH_XOR : unsigned(ADDR_WIDTH-1 downto 0) :=
    to_unsigned(2**SCRATCH_XOR_BIT, ADDR_WIDTH);

  -- Read-issue headroom. The fifo_128x4 IP is 256 beats deep, but gating a new
  -- read on the bare `full` flag leaves NO margin: `full` only asserts at the
  -- last beat, and by the time the read's response actually lands (read latency
  -- + the IP's own full/wr_data_count update latency) the FIFO can fill that
  -- last slot, so the 128-bit write overflows and the beat is DROPPED -- two
  -- program lines silently vanish. (Hardware-confirmed in the --long test /
  -- tb_sequencer_long: correct until the FIFO runs sustained-full, then periodic
  -- 2-line skips.) Gate instead on wr_data_count with FILL_MARGIN beats of slack
  -- (> one in-flight beat + count latency); costs a few beats of buffering.
  constant FIFO_BEATS  : natural := 256;                         -- IP depth (128-bit beats)
  constant FILL_MARGIN : natural := 8;                           -- headroom before issuing
  constant FILL_LIMIT  : unsigned(7 downto 0) :=
    to_unsigned(FIFO_BEATS - FILL_MARGIN, 8);                    -- issue a read only below this occupancy

begin

  fifo : fifo_128x4
    port map (
      rst           => fifo_rst,
      wr_clk        => ui_clk,
      rd_clk        => seq_clk,
      din           => fifo_din,
      wr_en         => fifo_wr_en,
      rd_en         => line_rd_en,
      dout          => line_dout,
      full          => fifo_full,
      empty         => line_empty,
      wr_data_count => fifo_wrcnt,
      rd_data_count => open
    );

  dbg_retry_count <= std_logic_vector(retry_count);
  dbg_hb_count    <= std_logic_vector(hb_count);

  -- primed: enough beats buffered for the sequencer to start without starving
  -- during the initial read-latency window. Derived from the write-side count
  -- (ui_clk domain); the sequencer must synchronise this single-bit level.
  primed <= '1' when unsigned(fifo_wrcnt) >= PRIME_BEATS else '0';

  process (ui_clk)
    variable cur_addr : unsigned(ADDR_WIDTH-1 downto 0);
  begin
    if rising_edge(ui_clk) then
      -- default single-cycle strobes
      fifo_wr_en <= '0';
      fifo_rst   <= '0';
      app_en     <= '0';

      if ui_rst = '1' then
        state       <= S_IDLE;
        rd_addr     <= to_unsigned(BASE_ADDR, ADDR_WIDTH);
        is_hb       <= '0';
        wait_ctr    <= (others => '0');
        hb_timer    <= (others => '0');
        retry_count <= (others => '0');
        hb_count    <= (others => '0');
        fifo_rst    <= '1';

      elsif restart = '1' then
        -- loop-back: flush the FIFO, rewind the address walk, and DRAIN any
        -- read that was in flight when the restart hit -- otherwise its
        -- (in-order, pre-restart) response would be pushed as if it were the
        -- first line of the rewound stream.
        state     <= S_DRAIN;
        drain_ctr <= to_unsigned(DRAIN_CYCLES, drain_ctr'length);
        rd_addr   <= to_unsigned(BASE_ADDR, ADDR_WIDTH);
        is_hb     <= '0';
        wait_ctr  <= (others => '0');
        hb_timer  <= (others => '0');
        fifo_rst  <= '1';

      elsif run = '1' then
        case state is

          when S_IDLE =>
            if unsigned(fifo_wrcnt) < FILL_LIMIT then
              -- enough headroom in the FIFO: issue a real sequential read
              app_addr <= std_logic_vector(rd_addr);
              app_cmd  <= "001";
              app_en   <= '1';
              is_hb    <= '0';
              state    <= S_WAIT_RDY;
            elsif hb_timer >= HEARTBEAT_CYCLES then
              -- FIFO full: keep the controller warm with a throwaway read to a
              -- DIFFERENT bank (so a real read later still does its own fresh
              -- ACTIVATE). Data is discarded.
              cur_addr := rd_addr xor SCRATCH_XOR;
              app_addr <= std_logic_vector(cur_addr);
              app_cmd  <= "001";
              app_en   <= '1';
              is_hb    <= '1';
              hb_timer <= (others => '0');
              state    <= S_WAIT_RDY;
            else
              hb_timer <= hb_timer + 1;
            end if;

          when S_WAIT_RDY =>
            -- hold the command until MIG accepts it (assert app_en only while
            -- unaccepted -- prevents the double-issue latch).
            if app_rdy = '1' then
              state    <= S_WAIT_VALID;
              wait_ctr <= (others => '0');
            else
              if is_hb = '1' then
                app_addr <= std_logic_vector(rd_addr xor SCRATCH_XOR);
              else
                app_addr <= std_logic_vector(rd_addr);
              end if;
              app_cmd <= "001";
              app_en  <= '1';
            end if;

          when S_WAIT_VALID =>
            if app_rd_data_valid = '1' then
              if is_hb = '1' then
                -- discard the warm-up read; do not push, do not advance
                hb_count <= hb_count + 1;
              else
                -- Half-order match (hardware-confirmed Phase 6c bring-up): the
                -- write-assembler packs the FIRST program line into the beat's
                -- LOW 64 bits, but the fifo_128x4 IP serialises a 128-bit word
                -- HIGH 64 bits first. Swap the halves on the way in so the FIFO
                -- emits the low half (first line) first -- otherwise every line
                -- pair comes out swapped (the analogue of the Phase 6b byte
                -- order). See memory/ddr3-streamer-phase6c.
                fifo_din   <= app_rd_data(63 downto 0) & app_rd_data(127 downto 64);
                fifo_wr_en <= '1';
                rd_addr    <= rd_addr + ADDR_INC;
              end if;
              state <= S_IDLE;
            elsif wait_ctr >= RETRY_TIMEOUT then
              -- lost command (app_rdy counted, no valid): re-issue same address
              retry_count <= retry_count + 1;
              state       <= S_IDLE;
            else
              wait_ctr <= wait_ctr + 1;
            end if;

          when others =>  -- S_DRAIN: after a restart, let any in-flight read's
            -- response arrive and be discarded (app_en stays deasserted, no
            -- push) before issuing fresh reads from the rewound address.
            if drain_ctr = 0 then
              state <= S_IDLE;
            else
              drain_ctr <= drain_ctr - 1;
            end if;

        end case;
      end if;
    end if;
  end process;

end architecture;
