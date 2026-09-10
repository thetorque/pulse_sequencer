-------------------------------------------------------------------------------
-- line_fifo_128x64  (SIMULATION MODEL)
--
-- Behavioural stand-in for the Xilinx fifo_generator IP used by
-- ddr3_line_streamer: 128-bit write / 64-bit read, independent clocks,
-- Standard FIFO (NOT FWFT). One 128-bit write becomes two 64-bit reads,
-- LOW 64 bits first (din[63:0] then din[127:64]).
--
-- This is a FUNCTIONAL model (in-order data, correct full/empty/counts). It is
-- NOT bit-accurate to the real IP's clock-domain-crossing timing -- simulation
-- cannot verify CDC metastability anyway. At integration this entity is
-- replaced by the generated IP; the half-ordering (low-first) must be matched
-- to the write-assembler's line packing on hardware, exactly as the Phase 6b
-- read path's byte order was matched.
--
-- Depth: 512 x 64-bit words = 256 x 128-bit beats.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity fifo_128x4 is
  port (
    rst           : in  std_logic;                      -- active high (async in this model)
    wr_clk        : in  std_logic;
    rd_clk        : in  std_logic;
    din           : in  std_logic_vector(127 downto 0);
    wr_en         : in  std_logic;
    rd_en         : in  std_logic;
    dout          : out std_logic_vector(63 downto 0);
    full          : out std_logic;                      -- cannot accept a 128-bit beat (< 2 words free)
    empty         : out std_logic;
    wr_data_count : out std_logic_vector(7 downto 0);   -- occupancy in 128-bit beats (0..255; full via 'full')
    rd_data_count : out std_logic_vector(8 downto 0)    -- occupancy in 64-bit words  (0..511)
  );
end entity;

architecture behav of fifo_128x4 is
  constant DEPTH  : integer := 512;          -- 64-bit words
  constant PWRAP  : integer := 2*DEPTH;      -- pointer range, extra bit disambiguates full/empty
  type mem_t is array(0 to DEPTH-1) of std_logic_vector(63 downto 0);
  signal mem    : mem_t := (others => (others => '0'));
  signal wr_ptr : integer range 0 to PWRAP-1 := 0;
  signal rd_ptr : integer range 0 to PWRAP-1 := 0;
  signal occ    : integer range 0 to PWRAP-1;   -- occupancy in words
begin

  -- combinational status derived from the two pointers (behavioural)
  occ           <= (wr_ptr - rd_ptr + PWRAP) mod PWRAP;
  empty         <= '1' when occ = 0 else '0';
  full          <= '1' when occ > DEPTH-2 else '0';   -- need room for 2 words (one beat)
  -- Data-count widths match the real IP: 9-bit read count (0..511), 8-bit write
  -- count (0..255). Neither can represent the completely-full depth (512 words /
  -- 256 beats) -- exactly as in the Xilinx IP, where 'full' signals full, not the
  -- count -- so saturate the top value instead of overflowing the vector.
  rd_data_count <= std_logic_vector(to_unsigned(occ, 9))   when occ   < 512 else std_logic_vector(to_unsigned(511, 9));
  wr_data_count <= std_logic_vector(to_unsigned(occ/2, 8)) when occ/2 < 256 else std_logic_vector(to_unsigned(255, 8));

  -- write side (one 128-bit beat -> two 64-bit words, low half first)
  wr_proc : process (wr_clk, rst)
  begin
    if rst = '1' then
      wr_ptr <= 0;
    elsif rising_edge(wr_clk) then
      if wr_en = '1' and (occ <= DEPTH-2) then
        mem(wr_ptr mod DEPTH)       <= din(63 downto 0);
        mem((wr_ptr+1) mod DEPTH)   <= din(127 downto 64);
        wr_ptr <= (wr_ptr + 2) mod PWRAP;
      end if;
    end if;
  end process;

  -- read side (Standard FIFO: data appears one rd_clk after rd_en)
  rd_proc : process (rd_clk, rst)
  begin
    if rst = '1' then
      rd_ptr <= 0;
      dout   <= (others => '0');
    elsif rising_edge(rd_clk) then
      if rd_en = '1' and occ /= 0 then
        dout   <= mem(rd_ptr mod DEPTH);
        rd_ptr <= (rd_ptr + 1) mod PWRAP;
      end if;
    end if;
  end process;

end architecture;
