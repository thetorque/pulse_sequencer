-- sideband_test.vhd -- Pico W sideband SPI1 loopback bring-up.
-- The Pico (SPI1 master) sends bytes; the ECP5 slave returns SIGNATURE(0xA5) then
-- echoes each previous byte, AND displays the last received byte on the LEDs.
-- Fabric clock = OSCG/10 (~31 MHz) so it comfortably oversamples the Pico SCK
-- (keep the Pico SCK <= a few MHz).
--
-- LEDs: g1..g6 = low 6 bits of the last received byte; r6 = heartbeat; r1..r5 off.
-- Safe defaults: AD9912 in reset, RF off, DAC shutdown.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity sideband_test is
  port (
    -- Pico sideband SPI1 slave
    pico_w_sck_aux, pico_w_tx_aux, pico_w_cs_aux : in  std_logic;
    pico_w_rx_aux, pico_w_attn : out std_logic;
    -- safe defaults
    dds_reset, dds_pwrdwn, rf_main_sw, vga_shdn : out std_logic;
    -- all LEDs (driven)
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of sideband_test is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(23 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';
  signal rx_byte   : std_logic_vector(7 downto 0);
  signal rx_valid  : std_logic;
begin

  osc : OSCG generic map ( DIV => 10 ) port map ( OSC => clk );   -- ~31 MHz

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

  u_sb : entity work.sideband_spi
    port map ( clk => clk, rst => rst,
               sck => pico_w_sck_aux, mosi => pico_w_tx_aux, cs => pico_w_cs_aux,
               miso => pico_w_rx_aux, attn => pico_w_attn,
               rx_byte => rx_byte, rx_valid => rx_valid );

  -- safe defaults
  dds_reset <= '1'; dds_pwrdwn <= '0'; rf_main_sw <= '0'; vga_shdn <= '0';

  -- LEDs: show low 6 bits of last received byte (active-low)
  led_g1 <= not rx_byte(0);
  led_g2 <= not rx_byte(1);
  led_g3 <= not rx_byte(2);
  led_g4 <= not rx_byte(3);
  led_g5 <= not rx_byte(4);
  led_g6 <= not rx_byte(5);
  led_r6 <= heartbeat;
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1';
end architecture;
