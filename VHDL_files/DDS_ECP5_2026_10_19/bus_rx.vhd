-- bus_rx.vhd -- DDS backplane bus receiver (slave side).
-- Implements DDS_BUS_CONTRACT.md v0.4 (repo root), sections 2, 4, 5, 8.
--
-- Physical: SPI mode 0, MSB first, CS-framed, SCK <= 33 MHz (25 MHz nominal).
-- bp_sck / bp_mosi / bp_cs are asynchronous; they are oversampled in clk through
-- identical 3-FF synchronisers (equal latency keeps MOSI aligned with SCK) and SCK
-- rising edges are edge-detected. clk must be >= ~5x SCK (dds_top: OSCG ~155 MHz).
-- (Scheme proven on hardware 1-33 MHz by bp_fast / bp_fast_rx.)
--
-- Frame (one CS-low period):
--   byte 0 : [7:5] version (must be 000)  [4:0] ADDR (0x1F = broadcast)
--   byte 1 : CMD
--   byte 2.: payload
-- Frames for another address (or a non-zero version) are ignored.
--
-- Commands:
--   0x01 WRITE_ROWS  START16 + N x 11-byte rows (big-endian, row bit 87 first).
--                    Each row is written to config_ram the moment its 11th byte
--                    arrives (address = START + i, wraps at 2^ADDR_W). A trailing
--                    partial row is dropped and flagged. rows_written pulses at the
--                    end of a frame that wrote >= 1 row (slave must re-preload).
--   0x02 RESET       no payload  -> cmd_reset pulse at frame end
--   0x03 STEP        no payload  -> cmd_step  pulse at frame end
--   0x04 WRITE_REG   REG16 + DATA8 -> reg_we pulse (reg_addr / reg_data) at frame end
--   0x05 IDENTIFY    SECS8         -> cmd_ident pulse (ident_secs) at frame end
--                                     (blink the identify LED for SECS s; 0 = stop)
--   0x06 CLEAR_STATUS no payload   -> cmd_clear pulse (clear latched error LEDs)
--   0x00 NOP         any payload, ignored
-- Wrong payload length / unknown CMD (for this board) -> frame_err pulse at frame end
-- (nothing executed for RESET/STEP/WRITE_REG; rows already completed stay written).
-- A partial byte at CS rise is discarded.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bus_rx is
  generic ( ADDR_W : integer := 13; DATA_W : integer := 88 );
  port (
    clk, rst   : in  std_logic;
    -- backplane bus (single-ended, after the DS90LV048A LVDS receivers; async)
    bp_sck     : in  std_logic;
    bp_mosi    : in  std_logic;
    bp_cs      : in  std_logic;
    board_addr : in  std_logic_vector(4 downto 0);
    -- write port into config_ram
    we    : out std_logic;
    waddr : out std_logic_vector(ADDR_W-1 downto 0);
    wdata : out std_logic_vector(DATA_W-1 downto 0);
    -- frame-end strobes (1 clk)
    rows_written : out std_logic;
    cmd_reset    : out std_logic;
    cmd_step     : out std_logic;
    reg_we       : out std_logic;
    reg_addr     : out std_logic_vector(15 downto 0);
    reg_data     : out std_logic_vector(7 downto 0);
    cmd_ident    : out std_logic;
    ident_secs   : out std_logic_vector(7 downto 0);
    cmd_clear    : out std_logic;
    frame_err    : out std_logic
  );
end entity;

architecture rtl of bus_rx is
  constant BROADCAST : std_logic_vector(4 downto 0) := "11111";
  constant OP_NOP   : std_logic_vector(7 downto 0) := x"00";
  constant OP_WROWS : std_logic_vector(7 downto 0) := x"01";
  constant OP_RESET : std_logic_vector(7 downto 0) := x"02";
  constant OP_STEP  : std_logic_vector(7 downto 0) := x"03";
  constant OP_WREG  : std_logic_vector(7 downto 0) := x"04";
  constant OP_IDENT : std_logic_vector(7 downto 0) := x"05";
  constant OP_CLEAR : std_logic_vector(7 downto 0) := x"06";
  constant ROW_BYTES : integer := DATA_W / 8;              -- 11

  -- synchronisers: (0) sck (1) mosi (2) cs ; cs resets to idle-high
  signal s1, s2, s3 : std_logic_vector(2 downto 0) := "100";

  signal shreg   : std_logic_vector(7 downto 0) := (others => '0');
  signal bitcnt  : integer range 0 to 7 := 0;
  signal byte_v  : std_logic := '0';                        -- 1-clk: byte complete
  signal byte_d  : std_logic_vector(7 downto 0) := (others => '0');

  signal nbytes  : integer range 0 to 7 := 0;               -- header/param bytes seen (saturates)
  signal active  : std_logic := '0';                        -- frame is for us
  signal ignore  : std_logic := '0';                        -- frame not for us
  signal cmd     : std_logic_vector(7 downto 0) := (others => '0');
  signal p16     : std_logic_vector(15 downto 0) := (others => '0');   -- START16 / REG16
  signal pdata   : std_logic_vector(7 downto 0) := (others => '0');
  signal row_sr  : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
  signal row_b   : integer range 0 to ROW_BYTES-1 := 0;     -- bytes into current row
  signal cur     : unsigned(ADDR_W-1 downto 0) := (others => '0');
  signal wrote   : std_logic := '0';
  signal extra   : std_logic := '0';                        -- payload longer than allowed
begin
  -- ---------------- bit level: sync, SCK edge, byte assembly ----------------
  process(clk) begin
    if rising_edge(clk) then
      s1 <= bp_cs & bp_mosi & bp_sck;
      s2 <= s1; s3 <= s2;
      byte_v <= '0';
      if rst = '1' or s2(2) = '1' then                      -- CS high: idle
        bitcnt <= 0;
      elsif s2(0) = '1' and s3(0) = '0' then                -- SCK rising, CS low
        shreg <= shreg(6 downto 0) & s2(1);
        if bitcnt = 7 then
          bitcnt <= 0;
          byte_v <= '1';
          byte_d <= shreg(6 downto 0) & s2(1);
        else
          bitcnt <= bitcnt + 1;
        end if;
      end if;
    end if;
  end process;

  -- ---------------- frame level ----------------
  process(clk)
    variable rowv : std_logic_vector(DATA_W-1 downto 0);
  begin
    if rising_edge(clk) then
      we <= '0'; rows_written <= '0'; cmd_reset <= '0'; cmd_step <= '0';
      reg_we <= '0'; frame_err <= '0'; cmd_ident <= '0'; cmd_clear <= '0';

      if rst = '1' then
        nbytes <= 0; active <= '0'; ignore <= '0'; wrote <= '0'; extra <= '0';
        row_b <= 0;

      elsif s2(2) = '0' and s3(2) = '1' then                -- CS falling: new frame
        nbytes <= 0; active <= '0'; ignore <= '0'; wrote <= '0'; extra <= '0';
        row_b <= 0;

      elsif s2(2) = '1' and s3(2) = '0' then                -- CS rising: frame end
        if active = '1' then
          case cmd is
            when OP_WROWS =>
              if wrote = '1' then rows_written <= '1'; end if;
              if nbytes < 4 or row_b /= 0 then frame_err <= '1'; end if;
            when OP_RESET =>
              if nbytes = 2 and extra = '0' then cmd_reset <= '1'; else frame_err <= '1'; end if;
            when OP_STEP =>
              if nbytes = 2 and extra = '0' then cmd_step <= '1'; else frame_err <= '1'; end if;
            when OP_WREG =>
              if nbytes = 5 and extra = '0' then
                reg_we <= '1'; reg_addr <= p16; reg_data <= pdata;
              else frame_err <= '1'; end if;
            when OP_IDENT =>
              if nbytes = 3 and extra = '0' then
                cmd_ident <= '1'; ident_secs <= pdata;
              else frame_err <= '1'; end if;
            when OP_CLEAR =>
              if nbytes = 2 and extra = '0' then cmd_clear <= '1'; else frame_err <= '1'; end if;
            when OP_NOP => null;
            when others => frame_err <= '1';
          end case;
        end if;                                             -- (header-only frame: no-op)
        active <= '0'; ignore <= '0';

      elsif byte_v = '1' and ignore = '0' then
        if nbytes = 0 then                                  -- header
          if byte_d(7 downto 5) = "000" and
             (byte_d(4 downto 0) = board_addr or byte_d(4 downto 0) = BROADCAST) then
            nbytes <= 1;
          else
            ignore <= '1';
          end if;
        elsif nbytes = 1 then                               -- command
          cmd <= byte_d; active <= '1'; nbytes <= 2;
        else
          case cmd is
            when OP_WROWS =>
              if nbytes = 2 then
                p16(15 downto 8) <= byte_d; nbytes <= 3;
              elsif nbytes = 3 then
                p16(7 downto 0) <= byte_d; nbytes <= 4;
                cur <= resize(unsigned(p16(15 downto 8) & byte_d), ADDR_W);
              else                                          -- row bytes
                rowv := row_sr(DATA_W-9 downto 0) & byte_d;
                row_sr <= rowv;
                if row_b = ROW_BYTES - 1 then
                  row_b <= 0;
                  we <= '1'; waddr <= std_logic_vector(cur); wdata <= rowv;
                  cur <= cur + 1; wrote <= '1';
                else
                  row_b <= row_b + 1;
                end if;
              end if;
            when OP_WREG =>
              if    nbytes = 2 then p16(15 downto 8) <= byte_d; nbytes <= 3;
              elsif nbytes = 3 then p16(7 downto 0)  <= byte_d; nbytes <= 4;
              elsif nbytes = 4 then pdata <= byte_d;            nbytes <= 5;
              else  extra <= '1';
              end if;
            when OP_IDENT =>
              if nbytes = 2 then pdata <= byte_d; nbytes <= 3; else extra <= '1'; end if;
            when OP_NOP => null;
            when others => extra <= '1';                    -- RESET/STEP/CLEAR/unknown: no payload
          end case;
        end if;
      end if;
    end if;
  end process;
end architecture;
