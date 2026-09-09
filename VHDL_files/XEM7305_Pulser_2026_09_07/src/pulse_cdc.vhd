-------------------------------------------------------------------------------
-- pulse_cdc  (Phase 6c -- clock-domain-crossing helpers)
--
-- Toggle-based single-pulse synchronizer: a 1-cycle pulse in the source clock
-- domain produces exactly one 1-cycle pulse in the destination domain, even
-- when the source clock is faster than the destination (a bare 1-cycle pulse
-- would otherwise be missed). Source pulses must be spaced a few destination
-- clocks apart -- true for the sequencer's per-loop `restart`.
--
-- Also a 2-FF level synchronizer (level_sync) for crossing a steady level such
-- as the streamer's `primed` into the sequencer's clock domain.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;

entity pulse_cdc is
  port (
    src_clk   : in  std_logic;
    src_pulse : in  std_logic;    -- 1-cycle pulse, src_clk domain
    dst_clk   : in  std_logic;
    dst_pulse : out std_logic     -- 1-cycle pulse, dst_clk domain
  );
end entity;

architecture rtl of pulse_cdc is
  signal tog        : std_logic := '0';
  signal s1, s2, s3 : std_logic := '0';
begin
  src : process (src_clk)
  begin
    if rising_edge(src_clk) then
      if src_pulse = '1' then
        tog <= not tog;           -- one toggle edge per source pulse
      end if;
    end if;
  end process;

  dst : process (dst_clk)
  begin
    if rising_edge(dst_clk) then
      s1 <= tog;  s2 <= s1;  s3 <= s2;   -- 2-FF sync (+1 for edge detect)
    end if;
  end process;

  dst_pulse <= s2 xor s3;         -- pulse on each synchronized toggle edge
end architecture;

-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;

entity level_sync is
  port (
    dst_clk : in  std_logic;
    d       : in  std_logic;
    q       : out std_logic
  );
end entity;

architecture rtl of level_sync is
  signal s1, s2 : std_logic := '0';
begin
  process (dst_clk)
  begin
    if rising_edge(dst_clk) then
      s1 <= d;  s2 <= s1;
    end if;
  end process;
  q <= s2;
end architecture;
