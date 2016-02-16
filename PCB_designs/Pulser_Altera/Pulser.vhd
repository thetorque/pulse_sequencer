--------------------------------------------------------------------------
-- Counters.vhd
--
-- HDL for the counters sample.  This HDL describes two counters operating
-- on different board clocks and with slightly different functionality.
-- The counter controls and counter values are connected to endpoints so
-- that FrontPanel may control and observe them.
--
-- Copyright (c) 2005-2009  Opal Kelly Incorporated
-- $Rev: 2 $ $Date: 2014-05-02 08:39:50 -0700 (Fri, 02 May 2014) $
--------------------------------------------------------------------------

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.std_logic_arith.all;
use IEEE.std_logic_misc.all;
use IEEE.std_logic_unsigned.all;

use work.FRONTPANEL.all;

entity Pulser is
	port (
		okUH      : in     STD_LOGIC_VECTOR(4 downto 0);
		okHU      : out    STD_LOGIC_VECTOR(2 downto 0);
		okUHU     : inout  STD_LOGIC_VECTOR(31 downto 0);
		okAA      : inout  STD_LOGIC;

		sys_clk   : in     STD_LOGIC;
		
		led       : out    STD_LOGIC_VECTOR(1 downto 0)
	);
end Pulser;

architecture arch of Pulser is
	signal okClk      : STD_LOGIC;
	signal okHE       : STD_LOGIC_VECTOR(112 downto 0);
	signal okEH       : STD_LOGIC_VECTOR(64 downto 0);
	signal okEHx      : STD_LOGIC_VECTOR(65*5-1 downto 0);
	
	signal ep00wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep20wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep21wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep22wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep40wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep60trig   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep61trig   : STD_LOGIC_VECTOR(31 downto 0);

	signal div1       : STD_LOGIC_VECTOR(23 downto 0);
	signal div2       : STD_LOGIC_VECTOR(23 downto 0);
	signal count1     : STD_LOGIC_VECTOR(7 downto 0);
	signal count2     : STD_LOGIC_VECTOR(7 downto 0);
	signal clk1div    : STD_LOGIC;
	signal clk2div    : STD_LOGIC;
	signal reset1     : STD_LOGIC;
	signal reset2     : STD_LOGIC;
	signal disable1   : STD_LOGIC;
	signal count1eq00 : STD_LOGIC;
	signal count1eq80 : STD_LOGIC;
	signal up2        : STD_LOGIC;
	signal down2      : STD_LOGIC;
	signal autocount2 : STD_LOGIC;
	signal count2eqFF : STD_LOGIC;
begin

reset1     <= ep00wire(0);
disable1   <= ep00wire(1);
autocount2 <= ep00wire(2);
ep20wire   <= (x"000000" & count1);
ep21wire   <= (x"000000" & count2);
ep22wire   <= x"00000000";
reset2     <= ep40wire(0);
up2        <= ep40wire(1);
down2      <= ep40wire(2);
ep60trig   <= (x"0000000" & "00" & count1eq80 & count1eq00);
ep61trig   <= (x"0000000" & "000" & count2eqFF);
led        <= not count1(3 downto 2);

-- Counter 1
-- + Counting using a divided sys_clk
-- + Reset sets the counter to 0.
-- + Disable turns off the counter.
process (sys_clk) begin
	if rising_edge(sys_clk) then
		div1 <= div1 - "1";
		if (div1 = x"000000") then
			div1 <= x"400000";
			clk1div <= '1';
		else
			clk1div <= '0';
		end if;
   
		if (clk1div = '1') then
			if (reset1 = '1') then
				count1 <= x"00";
			elsif (disable1 = '0') then
				count1 <= count1 + "1";
			end if;
		end if;
   
		if (count1 = x"00") then
			count1eq00 <= '1';
		else
			count1eq00 <= '0';
		end if;

		if (count1 = x"80") then
			count1eq80 <= '1';
		else
			count1eq80 <= '0';
		end if;
	end if;
end process;


-- Counter #2
-- + Reset, up, and down control counter.
-- + If autocount is enabled, a divided sys_clk can also
--   upcount.
process (sys_clk) begin
	if rising_edge(sys_clk) then
		div2 <= div2 - "1";
		if (div2 = x"000000") then
			div2 <= x"100000";
			clk2div <= '1';
		else
			clk2div <= '0';
		end if;

		if (reset2 = '1') then
			count2 <= x"00";
		elsif (up2 = '1') then
			count2 <= count2 + "1";
		elsif (down2 = '1') then
			count2 <= count2 - "1";
		elsif ((autocount2 = '1') and (clk2div = '1')) then
			count2 <= count2 + "1";
		end if;

		if (count2 = x"FF") then
			count2eqFF <= '1';
		else
			count2eqFF <= '0';
		end if;
	end if;
end process;

-- Instantiate the okHost and connect endpoints
okHI : okHost port map (
	okUH=>okUH, 
	okHU=>okHU, 
	okUHU=>okUHU, 
	okAA=>okAA,
	okClk=>okClk, 
	okHE=>okHE, 
	okEH=>okEH
);

okWO : okWireOR     generic map (N=>5) port map (okEH=>okEH, okEHx=>okEHx);

ep00 : okWireIn     port map (okHE=>okHE,                                    ep_addr=>x"00", ep_dataout=>ep00wire);
ep20 : okWireOut    port map (okHE=>okHE, okEH=>okEHx( 1*65-1 downto 0*65 ), ep_addr=>x"20", ep_datain=>ep20wire);
ep21 : okWireOut    port map (okHE=>okHE, okEH=>okEHx( 2*65-1 downto 1*65 ), ep_addr=>x"21", ep_datain=>ep21wire);
ep22 : okWireOut    port map (okHE=>okHE, okEH=>okEHx( 3*65-1 downto 2*65 ), ep_addr=>x"22", ep_datain=>ep22wire);
ep40 : okTriggerIn  port map (okHE=>okHE,                                    ep_addr=>x"40", ep_clk=>sys_clk, ep_trigger=>ep40wire);
ep60 : okTriggerOut port map (okHE=>okHE, okEH=>okEHx( 4*65-1 downto 3*65 ), ep_addr=>x"60", ep_clk=>sys_clk, ep_trigger=>ep60trig);
ep61 : okTriggerOut port map (okHE=>okHE, okEH=>okEHx( 5*65-1 downto 4*65 ), ep_addr=>x"61", ep_clk=>sys_clk, ep_trigger=>ep61trig);

end arch;