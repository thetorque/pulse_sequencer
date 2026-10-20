-- sim_oscg.vhd -- SIMULATION-ONLY model of the ECP5 OSCG primitive.
-- Provides a free-running clock so tops that instantiate OSCG can be simulated.
-- MUST NOT be included in synthesis (nextpnr maps the real OSCG primitive).

library ieee;
use ieee.std_logic_1164.all;

entity OSCG is
  generic ( DIV : integer := 128 );
  port ( OSC : out std_logic );
end entity;

architecture sim of OSCG is
  -- ~310 MHz / DIV; model as a simple square wave (exact rate irrelevant for logic sim)
  constant HALF : time := (161 ns * 128) / DIV;
begin
  process
  begin
    OSC <= '0'; wait for HALF;
    OSC <= '1'; wait for HALF;
  end process;
end architecture;
