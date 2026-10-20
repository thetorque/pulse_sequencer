-- dds_top.vhd -- DDS slave board ECP5 top-level SKELETON.
-- Wires the datapath to dds_ecp5.lpf (master pin file). Clock = internal OSCG.
-- Datapath: pulser backplane -> bus_rx -> config_ram -> ad9912_spi (+ dac_spi for
-- amplitude); pico sideband for standalone control. Sub-blocks are stubs for now
-- (safe idle) with real interfaces to fill in.
-- Safe power-up state: AD9912 held in reset during POR, RF off, DAC idle.
-- Diagnostics: LED g1..g5 show the strapped board address, g6 = heartbeat (alive).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dds_top is
  port (
    -- AD9912 DDS (ECP5 = SPI master)
    dds_sclk, dds_sdio, dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    dds_sdo : in std_logic;
    -- amplitude DAC / VGA (MCP4821 -> ADL5330)
    vga_sck, vga_sci, vga_cs, vga_ldac, vga_shdn : out std_logic;
    -- RF switch
    rf_main_sw : out std_logic;
    -- backplane / DDS bus (inputs via LVDS receivers)
    backplane_sck, backplane_mosi, backplane_cs,
    backplane_stepnext, backplane_ramreset,
    backplane_aux1, backplane_aux2, backplane_aux3 : in std_logic;
    -- Pico W sideband (SPI1 slave)
    pico_w_sck_aux, pico_w_tx_aux, pico_w_cs_aux : in std_logic;
    pico_w_rx_aux, pico_w_attn : out std_logic;
    -- board address straps
    add0, add1, add2, add3, add4 : in std_logic;
    -- PSRAM (QSPI, DNP)
    psram_sclk, psram_si, psram_so, psram_sio2, psram_sio3, psram_cen : out std_logic;
    -- aux / expansion
    aux0, aux1, aux2, aux3, aux4, aux5, aux6 : out std_logic;
    -- status LEDs (active-low)
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of dds_top is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  constant ADDR_W : integer := 10;
  constant DATA_W : integer := 88;

  signal clk : std_logic;
  signal por : unsigned(15 downto 0) := (others => '0');
  signal rst : std_logic := '1';

  signal hb_cnt     : unsigned(20 downto 0) := (others => '0');
  signal heartbeat  : std_logic := '1';
  signal board_addr : std_logic_vector(4 downto 0);

  signal sn_sync    : std_logic_vector(2 downto 0) := (others => '0');
  signal rr_sync    : std_logic_vector(1 downto 0) := (others => '0');
  signal step_pulse : std_logic;
  signal ram_rst    : std_logic;
  signal row_ptr    : unsigned(ADDR_W-1 downto 0) := (others => '0');

  signal ram_we    : std_logic;
  signal ram_waddr : std_logic_vector(ADDR_W-1 downto 0);
  signal ram_wdata : std_logic_vector(DATA_W-1 downto 0);
  signal ram_rdata : std_logic_vector(DATA_W-1 downto 0);
begin

  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );

  -- power-on reset: hold rst high for 2^16 cycles after config
  process(clk) begin
    if rising_edge(clk) then
      if por /= x"FFFF" then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
    end if;
  end process;

  -- heartbeat (~0.6 Hz)
  process(clk) begin
    if rising_edge(clk) then
      hb_cnt <= hb_cnt + 1;
      if hb_cnt = 0 then heartbeat <= not heartbeat; end if;
    end if;
  end process;

  board_addr <= add4 & add3 & add2 & add1 & add0;

  -- synchronize backplane broadcast lines; derive a rising-edge step pulse
  process(clk) begin
    if rising_edge(clk) then
      sn_sync <= sn_sync(1 downto 0) & backplane_stepnext;
      rr_sync <= rr_sync(0) & backplane_ramreset;
    end if;
  end process;
  step_pulse <= '1' when sn_sync(2 downto 1) = "01" else '0';
  ram_rst    <= rr_sync(1);

  -- row pointer: advance on step, clear on ram_reset / POR
  process(clk) begin
    if rising_edge(clk) then
      if rst = '1' or ram_rst = '1' then row_ptr <= (others => '0');
      elsif step_pulse = '1' then       row_ptr <= row_ptr + 1;
      end if;
    end if;
  end process;

  -- ============ datapath (stub blocks, real interfaces) ============
  u_ram : entity work.config_ram
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W )
    port map ( clk => clk, we => ram_we, waddr => ram_waddr, wdata => ram_wdata,
               raddr => std_logic_vector(row_ptr), rdata => ram_rdata );

  u_bus : entity work.bus_rx
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W )
    port map ( clk => clk, rst => rst,
               bp_sck => backplane_sck, bp_mosi => backplane_mosi, bp_cs => backplane_cs,
               board_addr => board_addr,
               we => ram_we, waddr => ram_waddr, wdata => ram_wdata );

  u_dds : entity work.ad9912_spi
    port map ( clk => clk, rst => rst, start => step_pulse, row => ram_rdata, busy => open,
               sclk => dds_sclk, sdio => dds_sdio, sdo => dds_sdo,
               csb => dds_csb, io_update => dds_ioupdate );

  u_dac : entity work.dac_spi
    port map ( clk => clk, rst => rst, start => step_pulse,
               code => ram_rdata(23 downto 12), busy => open,
               sck => vga_sck, sdi => vga_sci, cs => vga_cs, ldac => vga_ldac );

  u_sb : entity work.sideband_spi
    port map ( clk => clk, rst => rst,
               sck => pico_w_sck_aux, mosi => pico_w_tx_aux, cs => pico_w_cs_aux,
               miso => pico_w_rx_aux, attn => pico_w_attn );

  -- ============ top-driven control / safe defaults ============
  dds_reset  <= rst;    -- hold AD9912 in reset during POR, then release
  dds_pwrdwn <= '0';    -- powered
  rf_main_sw <= '0';    -- RF off by default  (TODO)
  vga_shdn   <= '1';    -- MCP4821 active (not shutdown)

  psram_sclk <= '0'; psram_cen <= '1';   -- PSRAM (DNP) disabled/idle
  psram_si <= '0'; psram_so <= '0'; psram_sio2 <= '0'; psram_sio3 <= '0';

  aux0 <= '0'; aux1 <= '0'; aux2 <= '0';  -- spare expansion, idle (TODO)
  aux3 <= '0'; aux4 <= '0'; aux5 <= '0'; aux6 <= '0';

  -- status LEDs (active-low): g1..g5 = board address bits, g6 = heartbeat
  led_g1 <= not board_addr(0);
  led_g2 <= not board_addr(1);
  led_g3 <= not board_addr(2);
  led_g4 <= not board_addr(3);
  led_g5 <= not board_addr(4);
  led_g6 <= heartbeat;
  led_r1 <= '1'; led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1';

  -- pin-retain: fan every otherwise-unused input into one output so no top-level
  -- port is trimmed while the datapath blocks are stubs (idle -> led_r6 off).
  led_r6 <= not ( dds_sdo xor backplane_sck xor backplane_mosi xor backplane_cs
                  xor backplane_aux1 xor backplane_aux2 xor backplane_aux3
                  xor pico_w_sck_aux xor pico_w_tx_aux xor pico_w_cs_aux );

end architecture;
