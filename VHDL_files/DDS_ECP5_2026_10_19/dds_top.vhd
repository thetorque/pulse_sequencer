-- dds_top.vhd -- DDS slave board ECP5 top level (DDS_BUS_CONTRACT.md v0.2).
-- Clocks: internal OSCG DIV=2 -> clk_f (~155 MHz, +-15 %) oversamples the backplane bus
-- (bus_rx, SCK <= 33 MHz) and writes config_ram. clk_s = clk_f / 2 (~77.5 MHz) runs the
-- rest (config_ram read port, dds_ctl, AD9912 / MCP4821 SPI): the EBR read path cannot
-- close at 155 MHz with yosys (no EBR output register). bus_rx events cross clk_f ->
-- clk_s through toggle synchronisers; config_ram_dc is a true dual-clock RAM.
--
-- Datapath:
--   backplane SCK/MOSI/CS -> bus_rx -> config_ram (8192 x 88-bit rows)
--                                   -> RESET / STEP / WRITE_REG / rows_written events
--   STEPNEXT / RAMRESET (rising edges) --------------------^ (OR'ed with the frame cmds)
--   dds_ctl: preload row k+1 into AD9912 (ad9912_spi) + MCP4821 (dac_spi, no auto-LDAC),
--            strobe IO_UPDATE + LDAC + RF switch on a step; AD9912 init after reset.
-- Pico sideband: still the loopback stub (sideband_spi).
--
-- Safe power-up: AD9912 held in reset during POR; after POR dds_ctl initialises it and
-- applies row 0 (all-zero table = 0 Hz, VGA 0, RF switch OPEN).
-- STEPNEXT / RAMRESET (sampled in clk_s) synchronisers start at '1' so an undriven
-- (fail-safe HIGH) line
-- produces no edge at power-up.
--
-- LEDs (active-low): g1..g5 = strapped board address, g6 = heartbeat (~1 Hz);
--   r1 = frame error seen (sticky), r2 = step overrun seen (sticky),
--   r3 = bus activity (frame for this board, ~0.1 s flash), r4 = RF switch ON,
--   r5 = row_ptr /= 0 (inside a sequence), r6 = idle-input pin-retain (normally off).

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

  constant ADDR_W : integer := 13;
  constant DATA_W : integer := 88;

  signal clk_f : std_logic;                         -- ~155 MHz (OSCG)
  signal clk_s : std_logic := '0';                  -- ~77.5 MHz (clk_f / 2)
  signal por   : unsigned(14 downto 0) := (others => '0');
  signal rst   : std_logic := '1';                  -- clk_s domain
  signal rst_f_sync : std_logic_vector(1 downto 0) := (others => '1');
  signal rst_f : std_logic;                         -- clk_f domain

  -- clk_f -> clk_s event crossing (toggle + 3-FF sync)
  signal tg_f   : std_logic_vector(4 downto 0) := (others => '0');   -- rows,reset,step,reg,err
  signal tg_s1, tg_s2, tg_s3 : std_logic_vector(4 downto 0) := (others => '0');
  signal ev_s   : std_logic_vector(4 downto 0);
  signal f_rows, f_reset, f_step, f_reg, f_err : std_logic;

  signal hb_cnt     : unsigned(25 downto 0) := (others => '0');   -- ~1.2 Hz @ 77.5 MHz
  signal act_cnt    : unsigned(22 downto 0) := (others => '0');   -- ~0.1 s flash
  signal board_addr : std_logic_vector(4 downto 0);

  signal sn_sync    : std_logic_vector(2 downto 0) := (others => '1');
  signal rr_sync    : std_logic_vector(2 downto 0) := (others => '1');
  signal line_step, line_reset : std_logic;

  signal ram_we    : std_logic;
  signal ram_waddr : std_logic_vector(ADDR_W-1 downto 0);
  signal ram_wdata : std_logic_vector(DATA_W-1 downto 0);
  signal ram_raddr : std_logic_vector(ADDR_W-1 downto 0);
  signal ram_rdata : std_logic_vector(DATA_W-1 downto 0);

  signal reg_addr : std_logic_vector(15 downto 0);
  signal reg_data : std_logic_vector(7 downto 0);

  signal ad_row_start, ad_reg_start, ad_busy : std_logic;
  signal ad_row       : std_logic_vector(87 downto 0);
  signal ad_reg_addr  : std_logic_vector(12 downto 0);
  signal ad_reg_data  : std_logic_vector(7 downto 0);
  signal dac_start, dac_busy, dac_ldac_unused : std_logic;
  signal dac_code     : std_logic_vector(11 downto 0);
  signal ldac_n, rf_sw, overrun : std_logic;
  signal row_ptr      : std_logic_vector(ADDR_W-1 downto 0);

  signal err_seen, ovr_seen : std_logic := '0';
begin

  osc : OSCG generic map ( DIV => 2 ) port map ( OSC => clk_f );

  -- clk_s = clk_f / 2 (fabric divider, promoted to a global; see dds_ecp5.lpf FREQUENCY)
  process(clk_f) begin
    if rising_edge(clk_f) then clk_s <= not clk_s; end if;
  end process;

  -- power-on reset in clk_s: hold rst high for 2^15 cycles (~0.42 ms) after config
  process(clk_s) begin
    if rising_edge(clk_s) then
      if por /= (por'range => '1') then por <= por + 1; rst <= '1'; else rst <= '0'; end if;
    end if;
  end process;
  process(clk_f) begin
    if rising_edge(clk_f) then rst_f_sync <= rst_f_sync(0) & rst; end if;
  end process;
  rst_f <= rst_f_sync(1);

  board_addr <= add4 & add3 & add2 & add1 & add0;

  -- broadcast lines: 3-FF sync in clk_s, rising-edge pulses (ignored during reset)
  process(clk_s) begin
    if rising_edge(clk_s) then
      sn_sync <= sn_sync(1 downto 0) & backplane_stepnext;
      rr_sync <= rr_sync(1 downto 0) & backplane_ramreset;
    end if;
  end process;
  line_step  <= '1' when sn_sync(2 downto 1) = "01" and rst = '0' else '0';
  line_reset <= '1' when rr_sync(2 downto 1) = "01" and rst = '0' else '0';

  -- ============ datapath ============
  u_ram : entity work.config_ram_dc
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W )
    port map ( wclk => clk_f, we => ram_we, waddr => ram_waddr, wdata => ram_wdata,
               rclk => clk_s, raddr => ram_raddr, rdata => ram_rdata );

  u_bus : entity work.bus_rx
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W )
    port map ( clk => clk_f, rst => rst_f,
               bp_sck => backplane_sck, bp_mosi => backplane_mosi, bp_cs => backplane_cs,
               board_addr => board_addr,
               we => ram_we, waddr => ram_waddr, wdata => ram_wdata,
               rows_written => f_rows, cmd_reset => f_reset, cmd_step => f_step,
               reg_we => f_reg, reg_addr => reg_addr, reg_data => reg_data,
               frame_err => f_err );

  -- bus_rx frame-end strobes -> clk_s pulses. Strobes are >= one frame (~1 us) apart,
  -- and reg_addr/reg_data stay stable until the next WRITE_REG frame, so the clk_s side
  -- may sample them when the reg pulse arrives.
  process(clk_f) begin
    if rising_edge(clk_f) then
      if rst_f = '0' then                          -- bus_rx strobes are defined from here on
        tg_f <= tg_f xor (f_err & f_reg & f_step & f_reset & f_rows);
      end if;
    end if;
  end process;
  process(clk_s) begin
    if rising_edge(clk_s) then
      tg_s1 <= tg_f; tg_s2 <= tg_s1; tg_s3 <= tg_s2;
    end if;
  end process;
  ev_s <= tg_s2 xor tg_s3;                         -- (0) rows (1) reset (2) step (3) reg (4) err

  u_ctl : entity work.dds_ctl
    generic map ( ADDR_W => ADDR_W, LDAC_CLKS => 12 )      -- LDAC low ~155 ns
    port map ( clk => clk_s, rst => rst,
               step_in => line_step or ev_s(2), reset_in => line_reset or ev_s(1),
               rows_in => ev_s(0), reg_in => ev_s(3),
               reg_addr => reg_addr, reg_data => reg_data,
               raddr => ram_raddr, rdata => ram_rdata,
               ad_row_start => ad_row_start, ad_row => ad_row,
               ad_reg_start => ad_reg_start, ad_reg_addr => ad_reg_addr,
               ad_reg_data => ad_reg_data, ad_busy => ad_busy,
               dac_start => dac_start, dac_code => dac_code, dac_busy => dac_busy,
               io_update => dds_ioupdate, ldac_n => ldac_n, rf_sw => rf_sw,
               row_ptr => row_ptr, armed => open, overrun => overrun );

  u_dds : entity work.ad9912_spi
    generic map ( DIV => 1 )                       -- SCLK ~39 MHz (AD9912 max 50 MHz)
    port map ( clk => clk_s, rst => rst,
               start_row => ad_row_start, row => ad_row,
               start_reg => ad_reg_start, reg_addr => ad_reg_addr, reg_data => ad_reg_data,
               busy => ad_busy, sclk => dds_sclk, sdio => dds_sdio, csb => dds_csb );

  u_dac : entity work.dac_spi
    generic map ( DIV => 3, AUTO_LDAC => false )   -- SCK ~13 MHz (MCP4821 max 20 MHz)
    port map ( clk => clk_s, rst => rst, start => dac_start, code => dac_code,
               busy => dac_busy, sck => vga_sck, sdi => vga_sci, cs => vga_cs,
               ldac => dac_ldac_unused );
  vga_ldac <= ldac_n;

  u_sb : entity work.sideband_spi
    port map ( clk => clk_s, rst => rst,
               sck => pico_w_sck_aux, mosi => pico_w_tx_aux, cs => pico_w_cs_aux,
               miso => pico_w_rx_aux, attn => pico_w_attn,
               rx_byte => open, rx_valid => open );

  -- ============ top-driven control / safe defaults ============
  dds_reset  <= rst;    -- hold AD9912 in reset during POR, then release
  dds_pwrdwn <= '0';    -- powered
  rf_main_sw <= rf_sw;  -- CTRL.RF_ON of the live row (open until a row turns it on)
  vga_shdn   <= '1';    -- MCP4821 active (not shutdown)

  psram_sclk <= '0'; psram_cen <= '1';   -- PSRAM (DNP) disabled/idle
  psram_si <= '0'; psram_so <= '0'; psram_sio2 <= '0'; psram_sio3 <= '0';

  aux0 <= '0'; aux1 <= '0'; aux2 <= '0';  -- spare expansion, idle
  aux3 <= '0'; aux4 <= '0'; aux5 <= '0'; aux6 <= '0';

  -- ============ status ============
  process(clk_s) begin
    if rising_edge(clk_s) then
      hb_cnt <= hb_cnt + 1;
      if rst = '1' then
        err_seen <= '0'; ovr_seen <= '0'; act_cnt <= (others => '0');
      else
        if ev_s(4)  = '1' then err_seen <= '1'; end if;
        if overrun  = '1' then ovr_seen <= '1'; end if;
        if ev_s(3 downto 0) /= "0000" then
          act_cnt <= (others => '1');                    -- ~0.1 s flash
        elsif act_cnt /= 0 then
          act_cnt <= act_cnt - 1;
        end if;
      end if;
    end if;
  end process;

  led_g1 <= not board_addr(0);
  led_g2 <= not board_addr(1);
  led_g3 <= not board_addr(2);
  led_g4 <= not board_addr(3);
  led_g5 <= not board_addr(4);
  led_g6 <= hb_cnt(25);
  led_r1 <= not err_seen;
  led_r2 <= not ovr_seen;
  led_r3 <= '0' when act_cnt /= 0 else '1';
  led_r4 <= not rf_sw;
  led_r5 <= '0' when unsigned(row_ptr) /= 0 else '1';

  -- pin-retain: fan the still-unused inputs into one output so no top-level port is
  -- trimmed (idle -> led_r6 off).
  led_r6 <= not ( dds_sdo xor backplane_aux1 xor backplane_aux2 xor backplane_aux3 );

end architecture;
