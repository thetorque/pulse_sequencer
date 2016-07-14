--------------------------------------------------------------------------------
-- Company: 
-- Engineer:
--
-- Create Date:   11:33:05 07/13/2016
-- Design Name:   
-- Module Name:   C:/Users/katori/Desktop/pulse_sequencer/VHDL_files/Pulser_w_2016_06_10/photon/testing.vhd
-- Project Name:  photon
-- Target Device:  
-- Tool versions:  
-- Description:   
-- 
-- VHDL Test Bench Created by ISE for module: photon
-- 
-- Dependencies:
-- 
-- Revision:
-- Revision 0.01 - File Created
-- Additional Comments:
--
-- Notes: 
-- This testbench has been automatically generated using types std_logic and
-- std_logic_vector for the ports of the unit under test.  Xilinx recommends
-- that these types always be used for the top-level I/O of a design in order
-- to guarantee that the testbench will bind correctly to the post-implementation 
-- simulation model.
--------------------------------------------------------------------------------
LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
 
-- Uncomment the following library declaration if using
-- arithmetic functions with Signed or Unsigned values
--USE ieee.numeric_std.ALL;
 
ENTITY testing IS
END testing;
 
ARCHITECTURE behavior OF testing IS 
 
    -- Component Declaration for the Unit Under Test (UUT)
 
    COMPONENT photon
    PORT(
         hi_in : IN  std_logic_vector(7 downto 0);
         hi_out : OUT  std_logic_vector(1 downto 0);
         hi_inout : INOUT  std_logic_vector(15 downto 0);
         hi_muxsel : OUT  std_logic;
         hi_aa : INOUT  std_logic;
         i2c_sda : OUT  std_logic;
         i2c_scl : OUT  std_logic;
         clk1 : IN  std_logic;
         pmt_input : IN  std_logic;
         logic_out : buffer   std_logic_vector(31 downto 0);
         logic_in : IN  std_logic_vector(3 downto 0);
         led : OUT  std_logic_vector(7 downto 0);
         dds_logic_data_out : OUT  std_logic_vector(15 downto 0);
         dds_logic_fifo_rd_clk : IN  std_logic;
         dds_logic_fifo_rd_en : IN  std_logic;
         dds_logic_fifo_rd_done : IN  std_logic;
         dds_logic_fifo_empty : OUT  std_logic;
         dds_logic_ram_reset : OUT  std_logic;
         dds_logic_step_to_next_value : OUT  std_logic;
         dds_logic_reset_dds_chip : OUT  std_logic;
         dds_logic_address : OUT  std_logic_vector(3 downto 0);
         dds_logic_debug_out : OUT  std_logic_vector(7 downto 0)
        );
    END COMPONENT;
    

   --Inputs
   signal hi_in : std_logic_vector(7 downto 0) := (others => '0');
   signal clk1 : std_logic := '0';
   signal pmt_input : std_logic := '0';
   signal logic_in : std_logic_vector(3 downto 0) := (others => '0');
   signal dds_logic_fifo_rd_clk : std_logic := '0';
   signal dds_logic_fifo_rd_en : std_logic := '0';
   signal dds_logic_fifo_rd_done : std_logic := '0';

	--BiDirs
   signal hi_inout : std_logic_vector(15 downto 0);
   signal hi_aa : std_logic;

 	--Outputs
   signal hi_out : std_logic_vector(1 downto 0);
   signal hi_muxsel : std_logic;
   signal i2c_sda : std_logic;
   signal i2c_scl : std_logic;
   signal logic_out : std_logic_vector(31 downto 0);
   signal led : std_logic_vector(7 downto 0);
   signal dds_logic_data_out : std_logic_vector(15 downto 0);
   signal dds_logic_fifo_empty : std_logic;
   signal dds_logic_ram_reset : std_logic;
   signal dds_logic_step_to_next_value : std_logic;
   signal dds_logic_reset_dds_chip : std_logic;
   signal dds_logic_address : std_logic_vector(3 downto 0);
   signal dds_logic_debug_out : std_logic_vector(7 downto 0);

   -- Clock period definitions
   constant clk1_period : time := 10 ns;
   constant dds_logic_fifo_rd_clk_period : time := 10 ns;
 
BEGIN
 
	-- Instantiate the Unit Under Test (UUT)
   uut: photon PORT MAP (
          hi_in => hi_in,
          hi_out => hi_out,
          hi_inout => hi_inout,
          hi_muxsel => hi_muxsel,
          hi_aa => hi_aa,
          i2c_sda => i2c_sda,
          i2c_scl => i2c_scl,
          clk1 => clk1,
          pmt_input => pmt_input,
          logic_out => logic_out,
          logic_in => logic_in,
          led => led,
          dds_logic_data_out => dds_logic_data_out,
          dds_logic_fifo_rd_clk => dds_logic_fifo_rd_clk,
          dds_logic_fifo_rd_en => dds_logic_fifo_rd_en,
          dds_logic_fifo_rd_done => dds_logic_fifo_rd_done,
          dds_logic_fifo_empty => dds_logic_fifo_empty,
          dds_logic_ram_reset => dds_logic_ram_reset,
          dds_logic_step_to_next_value => dds_logic_step_to_next_value,
          dds_logic_reset_dds_chip => dds_logic_reset_dds_chip,
          dds_logic_address => dds_logic_address,
          dds_logic_debug_out => dds_logic_debug_out
        );

   -- Clock process definitions
   clk1_process :process
   begin
		clk1 <= '0';
		wait for clk1_period/2;
		clk1 <= '1';
		wait for clk1_period/2;
   end process;
 
   dds_logic_fifo_rd_clk_process :process
   begin
		dds_logic_fifo_rd_clk <= '0';
		wait for dds_logic_fifo_rd_clk_period/2;
		dds_logic_fifo_rd_clk <= '1';
		wait for dds_logic_fifo_rd_clk_period/2;
   end process;
 

   -- Stimulus process
   stim_proc: process
   begin		
      -- hold reset state for 100 ns.
      wait for 100 ns;	

      wait for clk1_period*10;

      -- insert stimulus here 

      wait;
   end process;

END;
