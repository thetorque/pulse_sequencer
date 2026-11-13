-- dds_bus_tx.vhd -- Phase 4: DDS backplane bus master (XEM7305 side).
-- Implements DDS_BUS_CONTRACT.md v0.2 §2 + §7 (repo root).
--
-- Host -> BTPipeIn 0x81 -> async FIFO (32-bit, FWFT) -> this block (clk_100):
--   The pipe carries a byte stream of length-prefixed records:
--       record = LEN16 (big-endian) + LEN bytes of one complete DDS bus frame
--       LEN = 0 -> padding, skipped (the host pads every write to the BTPipe block size)
--   Each record becomes one CS-low frame on the backplane: SPI mode 0, MSB first,
--   SCK = clk / (4*HALF/2) (HALF = 2 -> 25 MHz from clk_100), then CS high for >= GAP
--   clocks (contract: >= 200 ns). If the FIFO runs dry mid-frame the bus simply pauses
--   with CS low and SCK low (the slave is edge-driven, so pauses are harmless).
--   Byte order inside a 32-bit pipe word: byte 0 of the host stream = bits 7:0
--   (LSB_FIRST = true, the FrontPanel USB 3 order); set false if the host order differs.
--
-- Broadcast lines (contract §7):
--   STEPNEXT = seq_step (sequencer channel 18, AdvanceDDS) OR a STRETCH-clock pulse on
--              trig_step (TriggerIn 0x40 bit 6, already crossed into clk)
--   RAMRESET = seq_reset (channel 19, ResetDDS) OR a pulse on trig_reset (0x40 bit 7)
--   All outputs are registered.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dds_bus_tx is
  generic (
    HALF      : integer := 2;          -- SCK half period in clk cycles (clk_100 -> 25 MHz)
    GAP       : integer := 30;         -- CS-high clocks after each frame (300 ns)
    STRETCH   : integer := 12;         -- trigger-generated STEPNEXT/RAMRESET width (120 ns)
    LSB_FIRST : boolean := true
  );
  port (
    clk, rst   : in  std_logic;
    -- FWFT FIFO read side
    fifo_dout  : in  std_logic_vector(31 downto 0);
    fifo_empty : in  std_logic;
    fifo_rd_en : out std_logic;
    -- step / reset sources
    seq_step, seq_reset   : in std_logic;   -- levels from master_logic(18)/(19)
    trig_step, trig_reset : in std_logic;   -- 1-clk pulses
    -- backplane (to the DS90LV047A drivers)
    bp_sck, bp_mosi, bp_cs, bp_step, bp_reset : out std_logic;
    -- status
    frame_active : out std_logic;
    frames_sent  : out std_logic_vector(15 downto 0)
  );
end entity;

architecture rtl of dds_bus_tx is
  type st_t is (M_LENH, M_LENL, M_FETCH, M_LO, M_HI, M_END, M_GAP);
  signal st    : st_t := M_LENH;
  signal wbuf  : std_logic_vector(31 downto 0) := (others => '0');
  signal wcnt  : integer range 0 to 4 := 0;            -- unread bytes in wbuf
  signal len   : unsigned(15 downto 0) := (others => '0');
  signal sh    : std_logic_vector(7 downto 0) := (others => '0');
  signal nbit  : integer range 0 to 7 := 0;
  signal hc    : integer range 0 to GAP := 0;
  signal nsent : unsigned(15 downto 0) := (others => '0');
  signal sck_r, mosi_r : std_logic := '0';
  signal cs_r  : std_logic := '1';
  signal st_cnt, rs_cnt : integer range 0 to STRETCH := 0;
  signal step_r, reset_r : std_logic := '0';
begin
  bp_sck <= sck_r; bp_mosi <= mosi_r; bp_cs <= cs_r;
  bp_step <= step_r; bp_reset <= reset_r;
  frame_active <= not cs_r;
  frames_sent  <= std_logic_vector(nsent);

  -- ---------------- frame serializer ----------------
  process(clk)
    variable have : boolean;                         -- a byte is available this cycle
    variable b    : std_logic_vector(7 downto 0);
  begin
    if rising_edge(clk) then
      fifo_rd_en <= '0';
      if rst = '1' then
        st <= M_LENH; wcnt <= 0; cs_r <= '1'; sck_r <= '0'; mosi_r <= '0'; hc <= 0;
        nsent <= (others => '0');
      else
        -- byte supply: take from wbuf, else refill wbuf from the FIFO (pop next cycle)
        have := false; b := (others => '0');
        if st = M_LENH or st = M_LENL or st = M_FETCH then
          if wcnt /= 0 then
            have := true;
            if LSB_FIRST then
              b := wbuf(7 downto 0);   wbuf <= x"00" & wbuf(31 downto 8);
            else
              b := wbuf(31 downto 24); wbuf <= wbuf(23 downto 0) & x"00";
            end if;
            wcnt <= wcnt - 1;
          elsif fifo_empty = '0' then
            wbuf <= fifo_dout; wcnt <= 4; fifo_rd_en <= '1';
          end if;
        end if;

        case st is
          when M_LENH =>
            if have then len(15 downto 8) <= unsigned(b); st <= M_LENL; end if;
          when M_LENL =>
            if have then
              len(7 downto 0) <= unsigned(b);
              if len(15 downto 8) = 0 and unsigned(b) = 0 then
                st <= M_LENH;                          -- padding record
              else
                cs_r <= '0'; st <= M_FETCH;           -- frame starts
              end if;
            end if;
          when M_FETCH =>
            sck_r <= '0';
            if have then sh <= b; nbit <= 0; hc <= 0; st <= M_LO; end if;
          when M_LO =>                                -- SCK low, MOSI = bit
            sck_r <= '0'; mosi_r <= sh(7);
            if hc = HALF-1 then hc <= 0; st <= M_HI; else hc <= hc + 1; end if;
          when M_HI =>                                -- SCK high: slave samples
            sck_r <= '1';
            if hc = HALF-1 then
              hc <= 0; sh <= sh(6 downto 0) & '0';
              if nbit = 7 then
                if len = 1 then st <= M_END; else len <= len - 1; st <= M_FETCH; end if;
              else
                nbit <= nbit + 1; st <= M_LO;
              end if;
            else
              hc <= hc + 1;
            end if;
          when M_END =>                               -- SCK low for a half period, CS high
            sck_r <= '0';
            if hc = HALF-1 then hc <= 0; cs_r <= '1'; nsent <= nsent + 1; st <= M_GAP;
            else hc <= hc + 1; end if;
          when M_GAP =>
            if hc = GAP-1 then hc <= 0; st <= M_LENH; else hc <= hc + 1; end if;
        end case;
      end if;
    end if;
  end process;

  -- ---------------- STEPNEXT / RAMRESET ----------------
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st_cnt <= 0; rs_cnt <= 0; step_r <= '0'; reset_r <= '0';
      else
        if trig_step = '1' then st_cnt <= STRETCH; elsif st_cnt /= 0 then st_cnt <= st_cnt - 1; end if;
        if trig_reset = '1' then rs_cnt <= STRETCH; elsif rs_cnt /= 0 then rs_cnt <= rs_cnt - 1; end if;
        if seq_step = '1' or st_cnt /= 0 then step_r <= '1'; else step_r <= '0'; end if;
        if seq_reset = '1' or rs_cnt /= 0 then reset_r <= '1'; else reset_r <= '0'; end if;
      end if;
    end if;
  end process;
end architecture;
