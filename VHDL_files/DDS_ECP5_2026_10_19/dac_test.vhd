-- dac_test.vhd -- MCP4821 amplitude-DAC bring-up: slow TRIANGLE sweep for DMM.
-- Ramps the 12-bit code 0 -> 4095 -> 0 continuously; VOUT = 2.048*code/4096,
-- so VOUT sweeps 0 V -> ~2.047 V -> 0 V.  Step every ~3.4 ms (2^13 / 2.4 MHz),
-- => ~14 s each way, ~28 s triangle period -- easy to follow on a multimeter.
-- Measure at the DAC VOUT / ADL5330 VDBS node.
--
-- Safe defaults: AD9912 held in reset, RF off.  LEDs: g1 = ramp direction
-- (lit = ramping up), g6 = heartbeat (alive).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dac_test is
  port (
    -- MCP4821 DAC port
    vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn : out std_logic;
    -- safe defaults
    dds_reset, dds_pwrdwn, rf_main_sw : out std_logic;
    -- all status LEDs (declared so none float)
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of dac_test is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(20 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';

  signal prescale  : unsigned(12 downto 0) := (others => '0');  -- ~3.4 ms/step
  signal code      : unsigned(11 downto 0) := (others => '0');
  signal dir       : std_logic := '0';                          -- '0' up, '1' down
  signal start     : std_logic := '0';
begin

  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
    end if;
  end process;

  process(clk) begin
    if rising_edge(clk) then
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  -- triangle generator + per-step DAC trigger
  process(clk)
  begin
    if rising_edge(clk) then
      start <= '0';
      if rst = '1' then
        prescale <= (others => '0'); code <= (others => '0'); dir <= '0';
      else
        prescale <= prescale + 1;
        if prescale = 0 then
          start <= '1';                       -- write current code to DAC each step
          if dir = '0' then
            if code = 4095 then dir <= '1'; code <= code - 1;
            else code <= code + 1; end if;
          else
            if code = 0 then dir <= '0'; code <= code + 1;
            else code <= code - 1; end if;
          end if;
        end if;
      end if;
    end if;
  end process;

  u_dac : entity work.dac_spi
    port map ( clk => clk, rst => rst, start => start,
               code => std_logic_vector(code), busy => open,
               sck => vga_sck, sdi => vga_sci, cs => vga_cs, ldac => vga_ldac );

  vga_shdn   <= '1';    -- MCP4821 active
  dds_reset  <= '1';    -- hold AD9912 in reset (safe; chip may be unpopulated)
  dds_pwrdwn <= '0';
  rf_main_sw <= '0';    -- RF off

  led_g1 <= dir;        -- active-low: lit while ramping up
  led_g6 <= heartbeat;
  -- all other LEDs explicitly OFF (driven high) so none float
  led_g2 <= '1'; led_g3 <= '1'; led_g4 <= '1'; led_g5 <= '1';
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1';
  led_r4 <= '1'; led_r5 <= '1'; led_r6 <= '1';
end architecture;
