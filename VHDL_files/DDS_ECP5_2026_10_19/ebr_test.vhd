-- ebr_test.vhd -- FULL-WIDTH, FULL-DEPTH config_ram (EBR) self-test.
-- Writes an 88-bit LFSR pattern into EVERY row (default 8192), reads them ALL
-- back, compares the full 88 bits, and reports via the LEDs.  The LFSR pattern
-- exercises all 88 bits of every row, so yosys keeps the RAM full width
-- (~40 DP16KD EBR blocks for 8192x88).
--
-- Result (after the ~10's-of-ms self-test, which completes before you can look):
--   GREEN LEDs blinking together  = PASS (every row's 88 bits read back correctly)
--   RED  LEDs (r1..r5) blinking   = FAIL (a mismatch)
--   r6 red always blinks          = heartbeat / alive
--
-- AW/HB are generics so the testbench can run a small, fast instance.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ebr_test is
  generic ( AW    : integer := 13;   -- 2^13 = 8192 rows (the full config table depth)
            HB    : integer := 22;   -- heartbeat counter width
            POR_W : integer := 16 ); -- power-on-reset counter width (short it for sim)
  port (
    dds_reset, dds_pwrdwn, rf_main_sw, vga_shdn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ebr_test is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  constant DW   : integer := 88;
  constant SEED : std_logic_vector(DW-1 downto 0) := x"A53C5A69F0112233445566";  -- nonzero
  constant LAST : unsigned(AW-1 downto 0) := (others => '1');

  constant POR_MAX : unsigned(POR_W-1 downto 0) := (others => '1');
  signal clk       : std_logic;
  signal por       : unsigned(POR_W-1 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(HB-1 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';

  type st_t is (S_WRITE, S_VERIFY, S_DONE);
  signal st    : st_t := S_WRITE;
  signal widx  : unsigned(AW-1 downto 0) := (others => '0');
  signal vidx  : unsigned(AW-1 downto 0) := (others => '0');
  signal vwait : unsigned(1 downto 0) := (others => '0');
  signal err   : std_logic := '0';
  signal lfsr  : std_logic_vector(DW-1 downto 0) := SEED;

  signal we    : std_logic := '0';
  signal waddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal raddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal wdata : std_logic_vector(DW-1 downto 0);
  signal rdata : std_logic_vector(DW-1 downto 0);

  signal pass_blink, fail_blink : std_logic;

  function adv(l : std_logic_vector(DW-1 downto 0)) return std_logic_vector is
  begin  -- Fibonacci LFSR (shift left, feed XOR of taps into bit 0)
    return l(DW-2 downto 0) & (l(DW-1) xor l(50) xor l(10) xor l(0));
  end function;
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  process(clk) begin
    if rising_edge(clk) then
      if por /= POR_MAX then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
    end if;
  end process;

  process(clk) begin
    if rising_edge(clk) then
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  u_ram : entity work.config_ram
    generic map ( ADDR_W => AW, DATA_W => DW )
    port map ( clk => clk, we => we, waddr => waddr, wdata => wdata,
               raddr => raddr, rdata => rdata );

  process(clk)
  begin
    if rising_edge(clk) then
      we <= '0';
      if rst = '1' then
        st <= S_WRITE; widx <= (others => '0'); vidx <= (others => '0');
        vwait <= (others => '0'); err <= '0'; lfsr <= SEED;
      else
        case st is
          when S_WRITE =>
            we    <= '1';
            waddr <= std_logic_vector(widx);
            wdata <= lfsr;
            if widx = LAST then
              st <= S_VERIFY; lfsr <= SEED; vwait <= (others => '0');
            else
              widx <= widx + 1; lfsr <= adv(lfsr);
            end if;

          when S_VERIFY =>
            raddr <= std_logic_vector(vidx);
            if vwait /= 2 then
              vwait <= vwait + 1;                     -- wait out registered-read latency
            else
              if rdata /= lfsr then err <= '1'; end if;   -- full 88-bit compare
              vwait <= (others => '0');
              if vidx = LAST then
                st <= S_DONE;
              else
                vidx <= vidx + 1; lfsr <= adv(lfsr);
              end if;
            end if;

          when S_DONE => null;
        end case;
      end if;
    end if;
  end process;

  pass_blink <= '1' when (st = S_DONE and err = '0' and heartbeat = '1') else '0';
  fail_blink <= '1' when (st = S_DONE and err = '1' and heartbeat = '1') else '0';

  dds_reset <= '1'; dds_pwrdwn <= '0'; rf_main_sw <= '0'; vga_shdn <= '0';

  -- active-low LEDs
  led_g1 <= not pass_blink; led_g2 <= not pass_blink; led_g3 <= not pass_blink;
  led_g4 <= not pass_blink; led_g5 <= not pass_blink; led_g6 <= not pass_blink;
  led_r1 <= not fail_blink; led_r2 <= not fail_blink; led_r3 <= not fail_blink;
  led_r4 <= not fail_blink; led_r5 <= not fail_blink;
  led_r6 <= heartbeat;      -- always-on heartbeat
end architecture;
