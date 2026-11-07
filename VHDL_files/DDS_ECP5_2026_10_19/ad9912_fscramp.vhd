-- ad9912_fscramp.vhd -- slow DAC full-scale-current (FSC) staircase for a DMM.
--
-- Steps FSC (live regs 0x040C[1:0] / 0x040B[7:0]) through 8 levels, 0x000 -> 0x3FF,
-- holding each ~3.5 s (2^23 OSCG clocks), then wraps back to 0x000 (~28 s sawtooth).
-- FSC is a LIVE register: no IO_UPDATE and no DDS clock needed, so the DC on DAC_OUT /
-- DAC_OUTB (pins 50/51) should follow the staircase on a DMM:
--   I_FS = 1.2V/R44(10k) * (72 + 192*FSC/1024)  ->  8.6 mA .. 31.7 mA
--   V_pin ~= I_FS/2 * R_eff  (R_eff ~37 ohm measured)  ->  ~0.16 V .. ~0.59 V
-- Step k (0..7) maps to FSC = k & k & k & k[2] (bit replication: 0 -> 0x000, 7 -> 0x3FF).
--
-- LEDs (active-low): g1..g3 = step k in binary (g1 = MSB), r1 = lit on the top step,
-- r6 = heartbeat.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_fscramp is
  port (
    dds_sclk, dds_sdio, dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ad9912_fscramp is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';

  signal step_cnt  : unsigned(22 downto 0) := (others => '0');  -- ~3.5 s per step
  signal k         : unsigned(2 downto 0) := (others => '0');
  signal fsc       : std_logic_vector(9 downto 0);
  signal started   : std_logic := '0';
  signal go        : std_logic := '0';

  type st_t is (IDLE, LOAD, BIT_LO, BIT_HI, CS_HI, GAP);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(23 downto 0) := (others => '0');
  signal cnt  : integer range 0 to 24 := 0;
  signal widx : integer range 0 to 1 := 0;
  signal gapc : integer range 0 to 7 := 0;
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  fsc <= std_logic_vector(k) & std_logic_vector(k) & std_logic_vector(k) & k(2);

  -- POR, heartbeat, step timer (write once right after reset, then every step)
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;

      go <= '0';
      if rst = '1' then
        step_cnt <= (others => '0'); k <= (others => '0'); started <= '0';
      else
        step_cnt <= step_cnt + 1;
        if started = '0' then
          started <= '1'; go <= '1';
        elsif step_cnt = (2**23 - 1) then
          k <= k + 1; go <= '1';             -- 7 -> 0 wraps the sawtooth
        end if;
      end if;
    end if;
  end process;

  -- write 0x040C (FSC[9:8]) then 0x040B (FSC[7:0]), each its own CSB cycle
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; dds_sclk <= '0'; dds_sdio <= '0'; dds_csb <= '1'; widx <= 0;
      else
        case st is
          when IDLE =>
            dds_sclk <= '0'; dds_csb <= '1';
            if go = '1' then widx <= 0; st <= LOAD; end if;
          when LOAD =>
            if widx = 0 then sh <= x"040C" & "000000" & fsc(9 downto 8);
            else             sh <= x"040B" & fsc(7 downto 0); end if;
            cnt <= 24; dds_csb <= '0'; st <= BIT_LO;
          when BIT_LO =>
            dds_sclk <= '0'; dds_sdio <= sh(23); st <= BIT_HI;
          when BIT_HI =>
            dds_sclk <= '1';
            if cnt = 1 then st <= CS_HI;
            else sh <= sh(22 downto 0) & '0'; cnt <= cnt - 1; st <= BIT_LO; end if;
          when CS_HI =>
            dds_sclk <= '0'; dds_csb <= '1'; gapc <= 4; st <= GAP;
          when GAP =>
            if gapc = 0 then
              if widx = 1 then st <= IDLE; else widx <= 1; st <= LOAD; end if;
            else gapc <= gapc - 1; end if;
        end case;
      end if;
    end if;
  end process;

  dds_ioupdate <= '0';
  dds_reset    <= rst;
  dds_pwrdwn   <= '0';

  led_g1 <= not k(2); led_g2 <= not k(1); led_g3 <= not k(0);
  led_g4 <= '1'; led_g5 <= '1'; led_g6 <= '1';
  led_r1 <= '0' when k = "111" else '1';
  led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1';
  led_r6 <= heartbeat;
end architecture;
