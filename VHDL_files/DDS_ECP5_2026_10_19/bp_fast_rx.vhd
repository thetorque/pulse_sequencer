-- bp_fast_rx.vhd -- backplane SPEED test, DDS-board side (checker). Pair with the
-- master's bp_fast (PRBS7 frames, SCK stepping 1 -> 33 MHz every ~10 s).
--
-- Oversamples SCK/MOSI/CS/STEPNEXT with the ECP5 internal oscillator at ~155 MHz
-- (OSCG DIV=2; +-15 %), the same "cross into clk and edge-detect" scheme bus_rx will use.
-- Checks, per ~0.5 s window:
--   MOSI      every bit sampled on an SCK rising edge (while CS low) matches the PRBS7
--             predicted from the previous 7 received bits (self-synchronising checker)
--   CS        every frame (CS low) contains exactly 32 SCK rising edges
--   STEPNEXT  exactly one STEPNEXT pulse between consecutive frames
-- LEDs (bicolor, active-low), refreshed every ~0.5 s:
--   D1  green = frames arriving            red = no frames
--   D2  green = MOSI/PRBS all bits OK      red = bit error(s)
--   D3  green = CS framing OK (32/frame)   red = wrong frame length(s)
--   D4  green = STEPNEXT OK (1/frame)      red = missing / extra pulse(s)
--   D6  green = everything OK              red = anything wrong
-- D2-D4 stay off while no frames arrive. The first window after load may show red
-- (checker not yet synchronised) -- ignore it.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bp_fast_rx is
  port (
    backplane_sck, backplane_mosi, backplane_cs, backplane_stepnext : in std_logic;
    backplane_ramreset, backplane_aux1, backplane_aux2, backplane_aux3 : in std_logic;
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of bp_fast_rx is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;

  constant WIN : integer := 77_500_000 - 1;           -- ~0.5 s @ ~155 MHz
  signal clk : std_logic;

  -- 3-stage synchronisers: index 0 SCK, 1 MOSI, 2 CS, 3 STEPNEXT
  signal raw, s1, s2, s3 : std_logic_vector(3 downto 0) := (others => '0');

  signal hist     : std_logic_vector(6 downto 0) := (others => '0');
  signal nseen    : integer range 0 to 7 := 0;        -- bits received since load (lock)
  signal bitcnt   : integer range 0 to 63 := 0;
  signal stepcnt  : integer range 0 to 3 := 0;
  signal first    : std_logic := '1';                 -- no frame completed yet

  signal wcnt : integer range 0 to WIN := 0;
  signal a_frames, a_bit, a_len, a_step : std_logic := '0';   -- accumulating this window
  signal d_frames, d_bit, d_len, d_step : std_logic := '0';   -- displayed (last window)
  signal ok_all : std_logic;
begin
  osc : OSCG generic map ( DIV => 2 ) port map ( OSC => clk );

  raw <= backplane_stepnext & backplane_cs & backplane_mosi & backplane_sck;

  process(clk)
    variable pred : std_logic;
  begin
    if rising_edge(clk) then
      s1 <= raw; s2 <= s1; s3 <= s2;

      -- SCK rising edge inside a frame: check + shift the PRBS bit
      if s2(0) = '1' and s3(0) = '0' and s2(2) = '0' then
        pred := hist(6) xor hist(5);
        if nseen = 7 and pred /= s2(1) then a_bit <= '1'; end if;
        hist <= hist(5 downto 0) & s2(1);
        if nseen < 7 then nseen <= nseen + 1; end if;
        if bitcnt < 63 then bitcnt <= bitcnt + 1; end if;
      end if;

      -- STEPNEXT rising edge
      if s2(3) = '1' and s3(3) = '0' then
        if stepcnt < 3 then stepcnt <= stepcnt + 1; end if;
      end if;

      -- CS falling = frame start: exactly one STEPNEXT since the previous frame
      if s2(2) = '0' and s3(2) = '1' then
        if first = '0' and stepcnt /= 1 then a_step <= '1'; end if;
        stepcnt <= 0;
        bitcnt  <= 0;
      end if;

      -- CS rising = frame end: exactly 32 bits
      if s2(2) = '1' and s3(2) = '0' then
        if first = '0' and bitcnt /= 32 then a_len <= '1'; end if;
        first    <= '0';
        a_frames <= '1';
      end if;

      -- display window
      if wcnt = WIN then
        wcnt <= 0;
        d_frames <= a_frames; d_bit <= a_bit; d_len <= a_len; d_step <= a_step;
        a_frames <= '0'; a_bit <= '0'; a_len <= '0'; a_step <= '0';
      else
        wcnt <= wcnt + 1;
      end if;
    end if;
  end process;

  ok_all <= d_frames and not d_bit and not d_len and not d_step;

  -- active-low LEDs
  led_g1 <= not d_frames;                 led_r1 <= d_frames;
  led_g2 <= not (d_frames and not d_bit); led_r2 <= not (d_frames and d_bit);
  led_g3 <= not (d_frames and not d_len); led_r3 <= not (d_frames and d_len);
  led_g4 <= not (d_frames and not d_step);led_r4 <= not (d_frames and d_step);
  led_g5 <= '1';                          led_r5 <= '1';
  led_g6 <= not ok_all;                   led_r6 <= ok_all;
end architecture;
