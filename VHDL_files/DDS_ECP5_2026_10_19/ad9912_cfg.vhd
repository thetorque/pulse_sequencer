-- ad9912_cfg.vhd -- AD9912 config + tone engine for first-light bring-up.
--
-- Plays a ROM of single-byte register writes over the SPI (mode 0, MSB-first, each
-- write in its own CSB cycle). The buffered FTW is transferred to the active DDS by
-- a REGISTER-UPDATE write (0x0005=0x01) at the END of the ROM -- over SPI, so it does
-- NOT depend on the IO_UPDATE pin (pin 60). The IO_UPDATE pin is also pulsed after,
-- as a redundant belt-and-braces. Triggered by a `start` pulse; asserts `busy`.
--
-- Generic CDIV sets the SPI speed: each SCLK half-period lasts CDIV clk cycles,
-- so SCLK = clk / (2*CDIV). CDIV=1 is full speed (clk/2 ~1.2 MHz); a larger CDIV
-- slows SCLK for easy scoping/decoding (e.g. CDIV=64 -> ~19 kHz).
--
-- Why this exists: ad9912_spi only writes POW/FTW, which is NOT enough for
-- first light. The AD9912 must be told to use its clock directly:
--   0x0010 = 0xD0  -> PD SYSCLK PLL (bit4)=1  => 400 MHz used DIRECTLY (no PLL),
--                     CMOS driver on (bit6), HSTL off (bit7).
-- DAC full-scale current (10-bit FSC, live regs): I_FS = 1.2V/R44 * (72 + 192*FSC/1024)
--   -> 8.6 mA (0x000) .. 31.7 mA (0x3FF). Value is set in the ROM below.
-- Frequency tuning word (48-bit, LSB @ 0x01A6 .. MSB @ 0x01AB), default below is
--   50 MHz @ 1 GHz sysclk = 0x0CCCCCCCCCCD.
--
-- Instruction word (16-bit): R/W=0 (write), W1:W0=00 (1 byte), A12:A0 = address.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ad9912_cfg is
  generic ( CDIV : integer := 1 );              -- clk cycles per SCLK half-period
  port (
    clk, rst  : in  std_logic;
    start     : in  std_logic;                  -- pulse: run the whole sequence
    busy      : out std_logic;
    sclk      : out std_logic;
    sdio      : out std_logic;                  -- MOSI
    sdo       : in  std_logic;                   -- MISO (unused here)
    csb       : out std_logic;                   -- active low
    io_update : out std_logic
  );
end entity;

architecture rtl of ad9912_cfg is
  type rom_t is array (natural range <>) of std_logic_vector(23 downto 0);
  constant ROM : rom_t := (
    x"0010D0",   -- 0x0010 = 0xD0 : bypass SYSCLK PLL (direct clock), CMOS on
    x"040C00",   -- 0x040C = 0x00 : DAC full-scale current [9:8]
    x"040B00",   -- 0x040B = 0x00 : DAC full-scale current [7:0]  (=> 0x000 min, 8.6 mA)
    x"01A6CD",   -- 0x01A6 = FTW[7:0]
    x"01A7CC",   -- 0x01A7 = FTW[15:8]
    x"01A8CC",   -- 0x01A8 = FTW[23:16]
    x"01A9CC",   -- 0x01A9 = FTW[31:24]
    x"01AACC",   -- 0x01AA = FTW[39:32]
    x"01AB0C",   -- 0x01AB = FTW[47:40]   (50 MHz @ 1 GHz = 0x0CCCCCCCCCCD)
    x"000501"    -- 0x0005 = 0x01 : REGISTER UPDATE over SPI (bit0, autoclear).
                 --   Transfers the buffered FTW to the active DDS WITHOUT relying on
                 --   the IO_UPDATE pin (pin 60), which may have a bad joint (pin 62/SDO
                 --   is confirmed open). SPI writes are proven good, so this is robust.
  );
  constant NREG : integer := ROM'length;
  constant NBITS: integer := 24;

  type st_t is (IDLE, LOAD, BIT_LO, BIT_HI, CS_HI, GAP, UPD_HI, UPD_LO);
  signal st   : st_t := IDLE;
  signal sh   : std_logic_vector(NBITS-1 downto 0) := (others => '0');
  signal cnt  : integer range 0 to NBITS := 0;
  signal idx  : integer range 0 to NREG := 0;
  signal updc : integer range 0 to 7 := 0;
  signal gapc : integer range 0 to 7 := 0;
  signal pre  : integer range 0 to CDIV-1 := 0; -- SCLK-rate prescaler
  signal start_seen : std_logic := '0';          -- latched so a 1-clk pulse isn't missed
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        st <= IDLE; sclk <= '0'; sdio <= '0'; csb <= '1'; io_update <= '0';
        busy <= '0'; idx <= 0; cnt <= 0; pre <= 0; start_seen <= '0';
      else
        if start = '1' then start_seen <= '1'; end if;   -- latch every clk

        if pre = CDIV-1 then
          pre <= 0;
          case st is                                     -- advance one FSM step
            when IDLE =>
              sclk <= '0'; csb <= '1'; io_update <= '0'; busy <= '0';
              if start_seen = '1' then
                start_seen <= '0'; idx <= 0; busy <= '1'; st <= LOAD;
              end if;

            when LOAD =>
              sh <= ROM(idx); cnt <= NBITS; csb <= '0'; st <= BIT_LO;

            when BIT_LO =>                              -- present MSB while clock low
              sclk <= '0'; sdio <= sh(NBITS-1); st <= BIT_HI;

            when BIT_HI =>                              -- rising edge: AD9912 samples
              sclk <= '1';
              if cnt = 1 then
                st <= CS_HI;
              else
                sh <= sh(NBITS-2 downto 0) & '0'; cnt <= cnt - 1; st <= BIT_LO;
              end if;

            when CS_HI =>
              sclk <= '0'; csb <= '1'; gapc <= 4; st <= GAP;

            when GAP =>
              if gapc = 0 then
                if idx = NREG - 1 then updc <= 3; st <= UPD_HI;
                else idx <= idx + 1; st <= LOAD; end if;
              else gapc <= gapc - 1; end if;

            when UPD_HI =>
              io_update <= '1';
              if updc = 0 then st <= UPD_LO; else updc <= updc - 1; end if;

            when UPD_LO =>
              io_update <= '0'; busy <= '0'; st <= IDLE;
          end case;
        else
          pre <= pre + 1;
        end if;
      end if;
    end if;
  end process;
end architecture;
