-- dds_top.vhd -- DDS slave board ECP5 top level (DDS_BUS_CONTRACT.md v0.4).
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
-- Power-up: AD9912 held in reset during POR; after POR dds_ctl initialises it and
-- applies row 0, whose power-up content is DEFAULT_ROW: 100 MHz, VGA 0x8DE (~-10 dBm
-- by the provisional board-8 calibration), RF switch ON -- a low, safe level even
-- unterminated. Rows 1.. power up zero (0 Hz, VGA 0, RF open). A loaded table
-- (WRITE_ROWS from row 0) replaces it; a RESET with no table loaded returns to it.
-- STEPNEXT / RAMRESET (sampled in clk_s) synchronisers start at '1' so an undriven
-- (fail-safe HIGH) line
-- produces no edge at power-up.
--
-- Front-panel LEDs: D1..D6 are bicolour (g = green, r = red, both = amber; active-low).
--   BOOT (first ~3.5 s after configuration, BOOT_BITS): D1..D5 = board address bits
--        0..4 (D1 = LSB), green = 1, red = 0 (so address 0 is five reds); D6 amber.
--   RUN:
--   D1 health    amber = AD9912 ID check / setup in progress
--                green blink (~0.6 Hz) = running, AD9912 part ID read back OK
--                red = AD9912 did not answer with its part ID (dead / unpowered chip)
--   D2 RF        green = RF switch ON (output live)
--   D3 bus       green flash = a frame for this board executed; red = frame error *
--   D4 step      green flash = STEPNEXT (line or frame); red = step overrun *
--   D5 sequence  green = inside a sequence (row_ptr /= 0); red flash = RESET (line/frame)
--   D6 identify  amber blink while an IDENTIFY command's timer runs
--   * latched until a CLEAR_STATUS frame (the host sends one at the start of every
--     table load, so red = "an error since this program was loaded").

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dds_top is
  generic (
    BOOT_BITS  : integer := 28;      -- boot address display: 2^28 clk_s ~ 3.5 s
    FLASH_BITS : integer := 23       -- activity flash: 2^23 clk_s ~ 0.11 s
  );
  port (
    -- AD9912 DDS (ECP5 = SPI master; SDIO bidirectional, 3-wire)
    dds_sclk, dds_csb, dds_ioupdate, dds_reset, dds_pwrdwn : out std_logic;
    dds_sdio : inout std_logic;
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

  -- FTW48 (100 MHz @ 1 GHz) | POW16 | VGA12 | rsvd4 | CTRL8 (RF_ON)
  constant DEFAULT_ROW : std_logic_vector(87 downto 0) :=
    x"19999999999A" & x"0000" & x"8DE" & x"0" & x"01";
  constant ADDR_W : integer := 13;
  constant DATA_W : integer := 88;

  signal clk_f : std_logic;                         -- ~155 MHz (OSCG)
  signal clk_s : std_logic := '0';                  -- ~77.5 MHz (clk_f / 2)
  signal por   : unsigned(14 downto 0) := (others => '0');
  signal rst   : std_logic := '1';                  -- clk_s domain
  signal rst_f_sync : std_logic_vector(1 downto 0) := (others => '1');
  signal rst_f : std_logic;                         -- clk_f domain

  -- clk_f -> clk_s event crossing (toggle + 3-FF sync)
  -- (0) rows (1) reset (2) step (3) reg (4) err (5) ident (6) clear
  signal tg_f   : std_logic_vector(6 downto 0) := (others => '0');
  signal tg_s1, tg_s2, tg_s3 : std_logic_vector(6 downto 0) := (others => '0');
  signal ev_s   : std_logic_vector(6 downto 0);
  signal f_rows, f_reset, f_step, f_reg, f_err, f_ident, f_clear : std_logic;
  signal ident_secs : std_logic_vector(7 downto 0);

  signal hb_cnt     : unsigned(25 downto 0) := (others => '0');   -- bit 25: ~0.6 Hz blink
  signal boot_cnt   : unsigned(BOOT_BITS-1 downto 0) := (others => '0');
  signal booting    : std_logic := '1';
  signal bus_cnt, stp_cnt : unsigned(FLASH_BITS-1 downto 0) := (others => '0');
  signal rrs_cnt    : unsigned(FLASH_BITS downto 0) := (others => '0');   -- ~0.2 s
  signal id_secs    : unsigned(7 downto 0) := (others => '0');
  signal id_tick    : unsigned(25 downto 0) := (others => '0');          -- ~0.87 s "second"
  signal board_addr : std_logic_vector(4 downto 0);
  signal sdio_o, sdio_oe : std_logic;
  signal ad_rd_start : std_logic;
  signal ad_rd_addr  : std_logic_vector(12 downto 0);
  signal ad_rd_data  : std_logic_vector(7 downto 0);
  signal init_done, id_ok : std_logic;
  signal ledg, ledr : std_logic_vector(6 downto 1);      -- '1' = lit

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
    generic map ( ADDR_W => ADDR_W, DATA_W => DATA_W, INIT_ROW0 => DEFAULT_ROW )
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
               cmd_ident => f_ident, ident_secs => ident_secs, cmd_clear => f_clear,
               frame_err => f_err );

  -- bus_rx frame-end strobes -> clk_s pulses. Strobes are >= one frame (~1 us) apart,
  -- and reg_addr/reg_data stay stable until the next WRITE_REG frame, so the clk_s side
  -- may sample them when the reg pulse arrives.
  process(clk_f) begin
    if rising_edge(clk_f) then
      if rst_f = '0' then                          -- bus_rx strobes are defined from here on
        tg_f <= tg_f xor (f_clear & f_ident & f_err & f_reg & f_step & f_reset & f_rows);
      end if;
    end if;
  end process;
  process(clk_s) begin
    if rising_edge(clk_s) then
      tg_s1 <= tg_f; tg_s2 <= tg_s1; tg_s3 <= tg_s2;
    end if;
  end process;
  ev_s <= tg_s2 xor tg_s3;   -- (0) rows (1) reset (2) step (3) reg (4) err (5) ident (6) clear

  u_ctl : entity work.dds_ctl
    generic map ( ADDR_W => ADDR_W, LDAC_CLKS => 12 )      -- LDAC low ~155 ns
    port map ( clk => clk_s, rst => rst,
               step_in => line_step or ev_s(2), reset_in => line_reset or ev_s(1),
               rows_in => ev_s(0), reg_in => ev_s(3),
               reg_addr => reg_addr, reg_data => reg_data,
               raddr => ram_raddr, rdata => ram_rdata,
               ad_row_start => ad_row_start, ad_row => ad_row,
               ad_reg_start => ad_reg_start, ad_reg_addr => ad_reg_addr,
               ad_reg_data => ad_reg_data,
               ad_rd_start => ad_rd_start, ad_rd_addr => ad_rd_addr, ad_rd_data => ad_rd_data,
               ad_busy => ad_busy,
               dac_start => dac_start, dac_code => dac_code, dac_busy => dac_busy,
               io_update => dds_ioupdate, ldac_n => ldac_n, rf_sw => rf_sw,
               row_ptr => row_ptr, armed => open, overrun => overrun,
               init_done => init_done, id_ok => id_ok );

  u_dds : entity work.ad9912_spi
    generic map ( DIV => 1 )                       -- SCLK ~39 MHz (AD9912 max 50 MHz)
    port map ( clk => clk_s, rst => rst,
               start_row => ad_row_start, row => ad_row,
               start_reg => ad_reg_start, reg_addr => ad_reg_addr, reg_data => ad_reg_data,
               start_rd => ad_rd_start, rd_addr => ad_rd_addr, rd_data => ad_rd_data,
               busy => ad_busy, sclk => dds_sclk,
               sdio_o => sdio_o, sdio_oe => sdio_oe, sdio_i => dds_sdio, csb => dds_csb );
  dds_sdio <= sdio_o when sdio_oe = '1' else 'Z';

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

  -- ============ status / front-panel LEDs ============
  process(clk_s) begin
    if rising_edge(clk_s) then
      hb_cnt <= hb_cnt + 1;
      if booting = '1' then
        boot_cnt <= boot_cnt + 1;
        if boot_cnt = (boot_cnt'range => '1') then booting <= '0'; end if;
      end if;
      if rst = '1' then
        err_seen <= '0'; ovr_seen <= '0';
        bus_cnt <= (others => '0'); stp_cnt <= (others => '0'); rrs_cnt <= (others => '0');
        id_secs <= (others => '0'); id_tick <= (others => '0');
      else
        -- latched errors: CLEAR_STATUS first, so an error in the same cycle still sticks
        if ev_s(6) = '1' then err_seen <= '0'; ovr_seen <= '0'; end if;
        if ev_s(4) = '1' then err_seen <= '1'; end if;
        if overrun = '1' then ovr_seen <= '1'; end if;
        -- flashes (retriggerable)
        if ev_s(0) = '1' or ev_s(1) = '1' or ev_s(2) = '1' or ev_s(3) = '1' or
           ev_s(5) = '1' or ev_s(6) = '1' then
          bus_cnt <= (others => '1');
        elsif bus_cnt /= 0 then bus_cnt <= bus_cnt - 1; end if;
        if line_step = '1' or ev_s(2) = '1' then stp_cnt <= (others => '1');
        elsif stp_cnt /= 0 then stp_cnt <= stp_cnt - 1; end if;
        if line_reset = '1' or ev_s(1) = '1' then rrs_cnt <= (others => '1');
        elsif rrs_cnt /= 0 then rrs_cnt <= rrs_cnt - 1; end if;
        -- identify timer (seconds ~ 2^26 clk_s; 0 = stop)
        if ev_s(5) = '1' then
          id_secs <= unsigned(ident_secs); id_tick <= (others => '0');
        elsif id_secs /= 0 then
          id_tick <= id_tick + 1;
          if id_tick = (id_tick'range => '1') then id_secs <= id_secs - 1; end if;
        end if;
      end if;
    end if;
  end process;

  process(all) begin
    ledg <= (others => '0'); ledr <= (others => '0');
    if booting = '1' then
      ledg(5 downto 1) <= board_addr;                  -- address, D1 = bit 0: 1 = green
      ledr(5 downto 1) <= not board_addr;              --                       0 = red
      ledg(6) <= '1'; ledr(6) <= '1';                  -- D6 amber
    else
      if init_done = '0' then                          -- D1 health
        ledg(1) <= '1'; ledr(1) <= '1';
      elsif id_ok = '1' then
        ledg(1) <= hb_cnt(25);
      else
        ledr(1) <= '1';
      end if;
      ledg(2) <= rf_sw;                                -- D2 RF on
      if bus_cnt /= 0 then ledg(3) <= '1'; end if;     -- D3 bus
      ledr(3) <= err_seen;
      if stp_cnt /= 0 then ledg(4) <= '1'; end if;     -- D4 step
      ledr(4) <= ovr_seen;
      if unsigned(row_ptr) /= 0 then ledg(5) <= '1'; end if;   -- D5 sequence
      if rrs_cnt /= 0 then ledr(5) <= '1'; end if;
      if id_secs /= 0 and hb_cnt(FLASH_BITS-1) = '1' then   -- D6 identify (~4.6 Hz blink)
        ledg(6) <= '1'; ledr(6) <= '1';
      end if;
    end if;
  end process;

  led_g1 <= not ledg(1); led_r1 <= not ledr(1);
  led_g2 <= not ledg(2); led_r2 <= not ledr(2);
  led_g3 <= not ledg(3); led_r3 <= not ledr(3);
  led_g4 <= not ledg(4); led_r4 <= not ledr(4);
  led_g5 <= not ledg(5); led_r5 <= not ledr(5);
  led_g6 <= not ledg(6);
  -- pin-retain: the still-unused inputs (AD9912 SDO, backplane AUX1-3) are folded into
  -- led_r6 through rst (only high during POR, when the LED state doesn't matter), so
  -- the ports aren't trimmed and their LPF LOCATEs stay valid.
  led_r6 <= not ledr(6) and not (rst and dds_sdo and backplane_aux1 and backplane_aux2
                                  and backplane_aux3);
end architecture;
