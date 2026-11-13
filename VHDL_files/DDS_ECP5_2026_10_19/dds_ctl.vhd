-- dds_ctl.vhd -- DDS board controller: config_ram rows -> AD9912 + VGA DAC + RF switch.
-- Implements DDS_BUS_CONTRACT.md v0.2 §6 (preload-then-strobe) on top of bus_rx events.
--
--   INIT     after reset: AD9912 setup writes (0x0010 = 0xD0 direct SYSCLK, DAC FSC =
--            0x200), then APPLY row 0.
--   PRELOAD  read row k+1, stream its POW+FTW into the AD9912 BUFFERED registers and its
--            VGA code into the MCP4821 input register (LDAC held high) -> "armed".
--   STEP     (STEPNEXT edge or STEP frame) when armed: IO_UPDATE + LDAC strobed in the
--            same clock, RF switch <= row.CTRL(0); row_ptr += 1; then PRELOAD the next.
--            The strobe starts 1 clk after step_in. A step that arrives while not armed
--            is kept (up to 3 pending) and fired as soon as the preload completes
--            ("late, not lost") and flagged on `overrun`.
--   RESET    (RAMRESET edge or RESET frame): row_ptr = 0, APPLY row 0 (load + strobe),
--            pending steps are discarded.
--   WRITE_REG: AD9912 register write, then re-APPLY the current row (the strobe also
--            commits any buffered register) and re-PRELOAD.
--   rows_written: re-PRELOAD row_ptr+1 (it may have been overwritten).
--   Priority when idle: reset > reg write > step > rows_written.
--
-- Row layout (§3): FTW48 [87:40] | POW16 [39:24] | VGA12 [23:12] | rsvd [11:8] | CTRL8 [7:0],
-- CTRL bit 0 = RF_ON.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dds_ctl is
  generic (
    ADDR_W    : integer := 13;
    UPD_CLKS  : integer := 4;                          -- IO_UPDATE high width (~26 ns)
    LDAC_CLKS : integer := 24                          -- LDAC low width (~155 ns, >= 100 ns)
  );
  port (
    clk, rst  : in  std_logic;
    -- events (1-clk pulses)
    step_in   : in  std_logic;
    reset_in  : in  std_logic;
    rows_in   : in  std_logic;
    reg_in    : in  std_logic;
    reg_addr  : in  std_logic_vector(15 downto 0);
    reg_data  : in  std_logic_vector(7 downto 0);
    -- config_ram read port (1-cycle registered read)
    raddr     : out std_logic_vector(ADDR_W-1 downto 0);
    rdata     : in  std_logic_vector(87 downto 0);
    -- AD9912 SPI engine
    ad_row_start : out std_logic;
    ad_row       : out std_logic_vector(87 downto 0);
    ad_reg_start : out std_logic;
    ad_reg_addr  : out std_logic_vector(12 downto 0);
    ad_reg_data  : out std_logic_vector(7 downto 0);
    ad_busy      : in  std_logic;
    -- MCP4821 SPI engine (AUTO_LDAC = false)
    dac_start : out std_logic;
    dac_code  : out std_logic_vector(11 downto 0);
    dac_busy  : in  std_logic;
    -- strobes / outputs
    io_update : out std_logic;
    ldac_n    : out std_logic;
    rf_sw     : out std_logic;
    -- status
    row_ptr   : out std_logic_vector(ADDR_W-1 downto 0);
    armed     : out std_logic;
    overrun   : out std_logic                          -- 1-clk pulse: step arrived unarmed
  );
end entity;

architecture rtl of dds_ctl is
  -- AD9912 setup writes after reset (a case statement, not an indexed constant array:
  -- yosys maps the array's index arithmetic onto a DSP multiplier -> slow path)
  constant N_INIT : integer := 3;
  --   0: 0x0010 = 0xD0 : PLL off, direct SYSCLK, CMOS driver on
  --   1: 0x040C = 0x02 : DAC FSC[9:8]  (FSC = 0x200)
  --   2: 0x040B = 0x00 : DAC FSC[7:0]

  type st_t is (S_INIT, S_REGW, S_RD, S_LOAD, S_WAIT, S_STROBE, S_IDLE);
  signal st      : st_t := S_INIT;
  signal init_i  : integer range 0 to N_INIT := 0;
  signal in_init : std_logic := '1';

  signal rp      : unsigned(ADDR_W-1 downto 0) := (others => '0');   -- live row
  signal target  : unsigned(ADDR_W-1 downto 0) := (others => '0');   -- row being loaded
  signal apply   : std_logic := '0';               -- 1: load + strobe (APPLY), 0: PRELOAD
  signal armed_i : std_logic := '0';
  signal pre_rf  : std_logic := '0';               -- CTRL.RF_ON of the preloaded row
  signal rowbuf  : std_logic_vector(87 downto 0) := (others => '0');
  signal rdwait  : integer range 0 to 3 := 0;            -- RAM read latency wait
  signal bwait   : integer range 0 to 3 := 0;
  signal scnt    : integer range 0 to 255 := 0;

  signal p_step  : integer range 0 to 3 := 0;
  signal p_reset, p_rows, p_reg : std_logic := '0';
  signal p_raddr : std_logic_vector(15 downto 0) := (others => '0');
  signal p_rdata : std_logic_vector(7 downto 0) := (others => '0');
begin
  raddr   <= std_logic_vector(target);
  row_ptr <= std_logic_vector(rp);
  armed   <= armed_i;
  ad_row  <= rowbuf;
  dac_code <= rowbuf(23 downto 12);

  process(clk)
    variable take_step : boolean;
    variable ps        : integer range 0 to 4;
  begin
    if rising_edge(clk) then
      ad_row_start <= '0'; ad_reg_start <= '0'; dac_start <= '0'; overrun <= '0';
      take_step := false;
      ps := p_step;

      if rst = '1' then
        st <= S_INIT; init_i <= 0; in_init <= '1';
        rp <= (others => '0'); target <= (others => '0'); armed_i <= '0'; apply <= '0';
        io_update <= '0'; ldac_n <= '1'; rf_sw <= '0'; pre_rf <= '0';
        p_step <= 0; p_reset <= '0'; p_rows <= '0'; p_reg <= '0';
      else
        -- ---------- event capture (any state) ----------
        if reset_in = '1' then p_reset <= '1'; end if;
        if rows_in  = '1' then p_rows  <= '1'; end if;
        if reg_in   = '1' then p_reg <= '1'; p_raddr <= reg_addr; p_rdata <= reg_data; end if;
        if step_in = '1' then
          if st = S_IDLE and armed_i = '1' and p_step = 0 and reset_in = '0' and
             p_reset = '0' and p_reg = '0' then
            take_step := true;                           -- fire right now (below)
          else
            if ps < 3 then ps := ps + 1; end if;
            overrun <= '1';
          end if;
        end if;

        -- ---------- sequencer ----------
        case st is
          when S_INIT =>                                 -- AD9912 setup register list
            if init_i = N_INIT then
              in_init <= '0'; target <= (others => '0'); apply <= '1';
              rdwait <= 2; st <= S_RD;
            else
              case init_i is
                when 0      => ad_reg_addr <= '0' & x"010"; ad_reg_data <= x"D0";
                when 1      => ad_reg_addr <= '0' & x"40C"; ad_reg_data <= x"02";
                when others => ad_reg_addr <= '0' & x"40B"; ad_reg_data <= x"00";
              end case;
              ad_reg_start <= '1';
              init_i <= init_i + 1; bwait <= 2; st <= S_REGW;
            end if;

          when S_REGW =>                                 -- wait for a register write
            if bwait /= 0 then bwait <= bwait - 1;
            elsif ad_busy = '0' then
              if in_init = '1' then st <= S_INIT;
              else                                       -- WRITE_REG: re-apply current row
                target <= rp; apply <= '1'; rdwait <= 2; st <= S_RD;
              end if;
            end if;

          when S_RD =>                                   -- config_ram read latency
            if rdwait /= 0 then rdwait <= rdwait - 1; else st <= S_LOAD; end if;

          when S_LOAD =>                                 -- start both SPI writes
            rowbuf <= rdata;
            ad_row_start <= '1'; dac_start <= '1';
            bwait <= 3; st <= S_WAIT;

          when S_WAIT =>
            if bwait /= 0 then bwait <= bwait - 1;
            elsif ad_busy = '0' and dac_busy = '0' then
              if apply = '1' then                        -- APPLY: strobe now
                rp <= target; armed_i <= '0';
                io_update <= '1'; ldac_n <= '0'; rf_sw <= rowbuf(0);
                scnt <= 0; st <= S_STROBE;
              else                                       -- PRELOAD done
                armed_i <= '1'; pre_rf <= rowbuf(0); st <= S_IDLE;
              end if;
            end if;

          when S_STROBE =>                               -- hold IO_UPDATE / LDAC widths
            scnt <= scnt + 1;
            if scnt = UPD_CLKS - 1 then io_update <= '0'; end if;
            if scnt = LDAC_CLKS - 1 then
              ldac_n <= '1';
              target <= rp + 1; apply <= '0'; rdwait <= 2; st <= S_RD;   -- PRELOAD next
            end if;

          when S_IDLE =>
            if p_reset = '1' or reset_in = '1' then
              p_reset <= '0'; ps := 0;
              target <= (others => '0'); apply <= '1'; armed_i <= '0'; rdwait <= 2; st <= S_RD;
            elsif p_reg = '1' then
              p_reg <= '0';
              ad_reg_addr <= p_raddr(12 downto 0); ad_reg_data <= p_rdata;
              ad_reg_start <= '1'; bwait <= 2; armed_i <= '0'; st <= S_REGW;
            elsif take_step or (ps /= 0 and armed_i = '1') then
              if not take_step then ps := ps - 1; end if;
              rp <= rp + 1; armed_i <= '0';
              io_update <= '1'; ldac_n <= '0'; rf_sw <= pre_rf;
              scnt <= 0; st <= S_STROBE;
            elsif p_rows = '1' then
              p_rows <= '0'; target <= rp + 1; apply <= '0'; armed_i <= '0';
              rdwait <= 2; st <= S_RD;
            end if;
        end case;

        p_step <= ps;
      end if;
    end if;
  end process;
end architecture;
