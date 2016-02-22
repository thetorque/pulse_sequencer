------------------------------------------------------------------------
--okLibrary.vhd 
--
--FrontPanel Library Module Declarations (VHDL)
-- ZEM4310
--
-- Copyright (c) 2004-2011 Opal Kelly Incorporated
-- $Rev: 8 $ $Date: 2014-07-25 16:12:33 -0700 (Fri, 25 Jul 2014) $
------------------------------------------------------------------------
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
package FRONTPANEL is

	attribute box_type: string;
	
	component okHost port (
		okUH   : in    std_logic_vector(4 downto 0);
		okHU   : out   std_logic_vector(2 downto 0);
		okUHU  : inout std_logic_vector(31 downto 0);
		okAA   : inout std_logic;
		okClk  : out   std_logic;
		okHE   : out   std_logic_vector(112 downto 0);
		okEH   : in    std_logic_vector(64 downto 0));
	end component;

	component okCoreHarness port (
		okHC   : in    std_logic_vector(38 downto 0);
		okCH   : out   std_logic_vector(37 downto 0);
		okHE   : out   std_logic_vector(112 downto 0);
		okEH   : in    std_logic_vector(64 downto 0));
	end component;

	component okWireIn port (
		okHE       : in  std_logic_vector(112 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_dataout : out std_logic_vector(31 downto 0));
	end component;

	component okWireOut port (
		okHE       : in  std_logic_vector(112 downto 0);
		okEH       : out std_logic_vector(64 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_datain  : in  std_logic_vector(31 downto 0));
	end component;

	component okTriggerIn port (
		okHE       : in  std_logic_vector(112 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_clk     : in  std_logic;
		ep_trigger : out std_logic_vector(31 downto 0));
	end component;

	component okTriggerOut port (
		okHE       : in  std_logic_vector(112 downto 0);
		okEH       : out std_logic_vector(64 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_clk     : in  std_logic;
		ep_trigger : in  std_logic_vector(31 downto 0));
	end component;

	component okPipeIn port (
		okHE       : in  std_logic_vector(112 downto 0);
		okEH       : out std_logic_vector(64 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_write   : out std_logic;
		ep_dataout : out std_logic_vector(31 downto 0));
	end component;

	component okPipeOut port (
		okHE       : in  std_logic_vector(112 downto 0);
		okEH       : out std_logic_vector(64 downto 0);
		ep_addr    : in  std_logic_vector(7 downto 0);
		ep_read    : out std_logic;
		ep_datain  : in  std_logic_vector(31 downto 0));
	end component;

	component okBTPipeIn port (
		okHE           : in  std_logic_vector(112 downto 0);
		okEH           : out  std_logic_vector(64 downto 0);
		ep_addr        : in  std_logic_vector(7 downto 0);
		ep_write       : out std_logic;
		ep_blockstrobe : out std_logic;
		ep_dataout     : out std_logic_vector(31 downto 0);
		ep_ready       : in  std_logic);
	end component;

	component okBTPipeOut port (
		okHE           : in  std_logic_vector(112 downto 0);
		okEH           : out std_logic_vector(64 downto 0);
		ep_addr        : in  std_logic_vector(7 downto 0);
		ep_read        : out std_logic;
		ep_blockstrobe : out std_logic;
		ep_datain      : in  std_logic_vector(31 downto 0);
		ep_ready       : in  std_logic);
	end component;
	
	component okRegisterBridge port (
		okHE           : in  std_logic_vector(112 downto 0);
		okEH           : out std_logic_vector(64 downto 0);
		ep_address     : out std_logic_vector(31 downto 0);
		ep_write       : out std_logic;
		ep_dataout     : out std_logic_vector(31 downto 0);
		ep_read        : out std_logic;
		ep_datain      : in  std_logic_vector(31 downto 0));
	end component;

	component okWireOR
	generic (N : integer := 1);
	port (
		okEH   : out std_logic_vector(64 downto 0);
		okEHx  : in  std_logic_vector(N*65-1 downto 0));
	end component;

end FRONTPANEL;