-- sideband_spi.vhd -- Pico W sideband SPI1 SLAVE (ECP5 side).
-- The Pico is SPI master (mode 0, MSB-first); the ECP5 receives command bytes and
-- returns a response full-duplex.  Oversampled in the fabric clock domain (clk must
-- be >> sck; keep the Pico SCK well below the OSCG fabric clock).
--
-- Response protocol (verifiable loopback for bring-up):
--   byte 0 of a CS frame -> returns SIGNATURE (0xA5)
--   byte N (N>=1)        -> returns byte N-1  (echo of the previous byte)
-- rx_byte/rx_valid expose each received byte to the fabric (command decode later).
-- attn asserts while a byte has been received in the current frame.
--
-- TODO (real use): assemble multi-byte {cmd,freq,amp} setpoints and hand them to
--                  the AD9912 streamer for standalone/CW operation.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity sideband_spi is
  port (
    clk, rst : in  std_logic;
    sck      : in  std_logic;
    mosi     : in  std_logic;
    cs       : in  std_logic;                     -- active low
    miso     : out std_logic;
    attn     : out std_logic;
    rx_byte  : out std_logic_vector(7 downto 0);  -- last byte received
    rx_valid : out std_logic                      -- 1-clk strobe per byte
  );
end entity;

architecture rtl of sideband_spi is
  constant SIG : std_logic_vector(7 downto 0) := x"A5";
  signal sck_r  : std_logic_vector(2 downto 0) := (others => '0');
  signal mosi_r : std_logic_vector(2 downto 0) := (others => '0');
  signal cs_r   : std_logic_vector(2 downto 0) := (others => '1');
  signal rxsh, txsh, lastrx : std_logic_vector(7 downto 0) := (others => '0');
  signal bitc      : integer range 0 to 7 := 0;
  signal byte_done : std_logic := '0';
begin
  process(clk)
    variable rx_now : std_logic_vector(7 downto 0);
  begin
    if rising_edge(clk) then
      -- synchronize the async SPI inputs (newest in bit 0)
      sck_r  <= sck_r(1 downto 0)  & sck;
      mosi_r <= mosi_r(1 downto 0) & mosi;
      cs_r   <= cs_r(1 downto 0)   & cs;

      rx_valid <= '0';

      if rst = '1' then
        bitc <= 0; byte_done <= '0'; miso <= '0'; attn <= '0';
        rxsh <= (others => '0'); txsh <= (others => '0'); lastrx <= (others => '0');
        rx_byte <= (others => '0');
      elsif cs_r(2 downto 1) = "10" then         -- CS falling edge: start of frame
        bitc <= 0; byte_done <= '0'; attn <= '0';
        txsh <= SIG; miso <= SIG(7);             -- present first response bit
      elsif cs_r(1) = '0' then                   -- CS active (settled low)
        -- SCK rising edge: sample MOSI
        if sck_r(2 downto 1) = "01" then
          rx_now := rxsh(6 downto 0) & mosi_r(1);
          rxsh <= rx_now;
          if bitc = 7 then
            rx_byte  <= rx_now;
            lastrx   <= rx_now;
            rx_valid <= '1';
            attn     <= '1';
            byte_done <= '1';
            bitc     <= 0;
          else
            bitc <= bitc + 1;
          end if;
        end if;
        -- SCK falling edge: advance the MISO shifter
        if sck_r(2 downto 1) = "10" then
          if byte_done = '1' then                -- load echo for the next byte
            txsh <= lastrx; miso <= lastrx(7); byte_done <= '0';
          else
            txsh <= txsh(6 downto 0) & '0'; miso <= txsh(6);
          end if;
        end if;
      else                                       -- CS idle (high)
        attn <= '0';
      end if;
    end if;
  end process;
end architecture;
