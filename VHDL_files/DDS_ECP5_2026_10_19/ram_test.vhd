-- ram_test.vhd -- config_ram (ECP5 EBR) bring-up with LED display.
-- Phase 1 WRITE : store a walking-one pattern (1 << (addr mod 6)) in rows 0..15.
-- Phase 2 VERIFY: read each row back, compare to what was written; set 'err' on mismatch.
-- Phase 3 RUN   : slowly cycle the read address; show rdata(5:0) on the green LEDs.
--
-- Visual result: a single GREEN LED walks across D-positions = the stored data read
-- back from RAM.  led_r1 RED lit = a verify mismatch (RAM fault).  led_r6 = heartbeat.
-- (So: walking green + red OFF = RAM write/read/addressing all good.)

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ram_test is
  port (
    dds_reset, dds_pwrdwn, rf_main_sw, vga_shdn : out std_logic;   -- safe defaults
    led_g1, led_g2, led_g3, led_g4, led_g5, led_g6 : out std_logic;
    led_r1, led_r2, led_r3, led_r4, led_r5, led_r6 : out std_logic
  );
end entity;

architecture rtl of ram_test is
  component OSCG
    generic ( DIV : integer := 128 );
    port ( OSC : out std_logic );
  end component;

  constant AW : integer := 10;   -- 1024 rows -> forces real EBR (DP16KD) inference
  constant DW : integer := 88;   -- real config row width
  -- we only use rows 0..15 (idx counters are 4-bit, zero-extended to the RAM addr)

  signal clk       : std_logic;
  signal por       : unsigned(15 downto 0) := (others => '0');
  signal rst       : std_logic := '1';
  signal hb_cnt    : unsigned(21 downto 0) := (others => '0');
  signal heartbeat : std_logic := '1';

  type st_t is (S_WRITE, S_VERIFY, S_RUN);
  signal st   : st_t := S_WRITE;
  signal widx : unsigned(3 downto 0) := (others => '0');   -- rows 0..15
  signal vidx : unsigned(3 downto 0) := (others => '0');
  signal ridx : unsigned(3 downto 0) := (others => '0');
  signal vwait : unsigned(1 downto 0) := (others => '0');
  signal err  : std_logic := '0';
  signal prescale : unsigned(21 downto 0) := (others => '0');

  signal we    : std_logic := '0';
  signal waddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal raddr : std_logic_vector(AW-1 downto 0) := (others => '0');
  signal wdata : std_logic_vector(DW-1 downto 0) := (others => '0');
  signal rdata : std_logic_vector(DW-1 downto 0);

  -- walking-one in the low 6 bits, by address
  function pat(a : unsigned) return std_logic_vector is
    variable r : std_logic_vector(DW-1 downto 0) := (others => '0');
  begin
    r(to_integer(a) mod 6) := '1';
    return r;
  end function;
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );   -- ~2.4 MHz

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
        ridx <= (others => '0'); vwait <= (others => '0'); err <= '0';
        prescale <= (others => '0');
      else
        case st is
          when S_WRITE =>
            we    <= '1';
            waddr <= std_logic_vector(resize(widx, AW));
            wdata <= pat(widx);
            if widx = 15 then st <= S_VERIFY; vwait <= (others => '0');
            else widx <= widx + 1; end if;

          when S_VERIFY =>
            raddr <= std_logic_vector(resize(vidx, AW));  -- hold addr while RAM reads
            if vwait /= 2 then
              vwait <= vwait + 1;                     -- wait out the registered-read latency
            else
              if rdata(5 downto 0) /= pat(vidx)(5 downto 0) then err <= '1'; end if;
              vwait <= (others => '0');
              if vidx = 15 then st <= S_RUN;
              else vidx <= vidx + 1; end if;
            end if;

          when S_RUN =>
            raddr <= std_logic_vector(resize(ridx, AW));
            prescale <= prescale + 1;
            if prescale = 0 then ridx <= ridx + 1; end if;  -- ~1.7 s/step
        end case;
      end if;
    end if;
  end process;

  -- safe defaults
  dds_reset <= '1'; dds_pwrdwn <= '0'; rf_main_sw <= '0'; vga_shdn <= '0';

  -- display: rdata low 6 bits on greens (active-low) = the walking pattern from RAM
  led_g1 <= not rdata(0);
  led_g2 <= not rdata(1);
  led_g3 <= not rdata(2);
  led_g4 <= not rdata(3);
  led_g5 <= not rdata(4);
  led_g6 <= not rdata(5);
  led_r1 <= not err;    -- RED lit = verify mismatch (RAM fault)
  led_r6 <= heartbeat;
  led_r2 <= '1'; led_r3 <= '1'; led_r4 <= '1'; led_r5 <= '1';
end architecture;
