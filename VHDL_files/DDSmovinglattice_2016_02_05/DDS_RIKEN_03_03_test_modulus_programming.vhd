
library ieee;
use ieee.std_logic_1164.all;
USE ieee.std_logic_arith.all;
use ieee.numeric_std.all;
USE work.all;

entity DDS_RIKEN is
  port(
    clk_dds : in std_logic; -- clock in from DDS divided clock
	 clk_in0: in std_logic; --clock in from local oscillator of 25 MHz

    -- LED driver ---
	 LED_CLK: OUT STD_LOGIC;
	 LED_SDI: OUT STD_LOGIC_VECTOR (0 DOWNTO 0);
	 LED_LE: OUT STD_LOGIC;
	 LED_OE: OUT STD_LOGIC;
	 
	 -- DDS comminucation port --
	 dds_port: out std_logic_vector (31 downto 0);
	 dds_master_reset: out std_logic;
	 dds_osk: out std_logic;
	 dds_io_update: out std_logic;
	 dds_drover: in std_logic;
	 dds_drhold: out std_logic;
	 dds_drctl: out std_logic;
	 
	 -- function pins for dds --
	 f_pin: out std_logic_vector (3 downto 0);
	 --profile select pins--
	 ps: out std_logic_vector (2 downto 0);
	 
	 
	 -- DAC control pin --
	 
	 dac_out : out std_LOGIC_VECTOR (13 downto 0);
	 dac_wr_pin: out std_logic;
	 
	 
	 ----address set pins----
	 add_in: in std_logic_vector (3 downto 0) -- set address of the DDS board (4bit)
    );

end DDS_RIKEN;

architecture behaviour of DDS_RIKEN is
	signal led_value: STD_LOGIC_VECTOR (7 downto 0);
	signal clk_system: STD_LOGIC;
	
	---- declare signal for use in parallel programming mode ----
	signal par_16_bit: STD_LOGIC_vector(0 downto 0); -- '0' = 8 bit; '1' = 16 bit
	signal par_rd: STD_LOGIC_vector(0 downto 0); -- read pin
	signal par_wr: STD_LOGIC_vector(0 downto 0); -- write pin
	signal par_add: STD_LOGIC_VECTOR(7 downto 0); -- parallel protocol address
	signal par_data: STD_LOGIC_VECTOR(15 downto 0); -- parallel protocol data
	
	---- amplitude for gain variable amp ----
	
	signal main_amplitude: std_logic_vector(13 downto 0);



begin

	led_value <= "00001111";
	
	--- ground unused pins ---
	dds_osk <= '0';
	dds_drhold <= '0';
	dds_drctl <= '0';
	
	----- Test DDS functionality ------
	f_pin <= "0000"; --- Parallel programming mode
	----- assign various data to the dds bus ---
	dds_port(31 downto 16) <= par_data(15 downto 0);
	dds_port(15 downto 8) <= par_add(7 downto 0);
	dds_port(0 downto 0) <= par_16_bit;
	dds_port(1 downto 1) <= par_rd;
	dds_port(2 downto 2) <= par_wr;
	dds_port(7 downto 3) <= "00000";
	
	main_amplitude <= "01111111111111";
	
	par_16_bit <= "1";
	--dds_master_reset <= '0';
	ps <= "000"; --- select profile 0
	par_rd <= "0";
	
	---- write instruction to DDS ---
	PROCESS (clk_in0)
		variable main_count: integer range 0 to 35:=0;
	BEGIN
		IF (clk_in0'event and clk_in0='0') then
			CASE main_count IS
				WHEN 0 => dds_io_update <= '0';
				          dds_master_reset <='0';
							 main_count := main_count+1;
				WHEN 1 => dds_io_update <= '0';
				          dds_master_reset <='1';
							 main_count := main_count+1;
				WHEN 2 => dds_io_update <= '0';
				          dds_master_reset <='0';
							 main_count := main_count+1;
				----- Profile 0 frequency			 
				WHEN 3 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 4 => par_add <= "00101111";
							 par_data <= "0000000000001000";
							 main_count := main_count+1;
				WHEN 5 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 6 => par_wr <="1";
							 main_count := main_count+1;
				
--				WHEN 7 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 8 => par_add <= "00000111";
--							 par_data <= "0000000010000001";--- CRF2 -- enable profile (23), enable modulus mode (16)
--							 main_count := main_count+1;
--				WHEN 9 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 10 => par_wr <="1";
--							 main_count := main_count+1;


				WHEN 7 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 8 => par_add <= "00000111";
							 par_data <= "0000000010001001";--- CRF2 -- enable profile (23), enable modulus mode (16)
							 --par_data <= "0000000010000000";--- CRF2 -- enable profile (23), enable modulus mode (16)
							 main_count := main_count+1;
				WHEN 9 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 10 => par_wr <="1";
							 main_count := main_count+1;
							 
				-------- program A and B for modulus mode testing

				---- A --> 1
				WHEN 11 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 12 => par_add <= "00011001";---0x19
							 par_data <= "0000000000000000";--- 1
							 main_count := main_count+1;
				WHEN 13 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 14 => par_wr <="1";
							 main_count := main_count+1;
							 
				WHEN 15 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 16 => par_add <= "00011011";---0x1B
							 par_data <= "0000000000000000";--- 
							 main_count := main_count+1;
				WHEN 17 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 18 => par_wr <="1";
							 main_count := main_count+1;
							 
				---- B -> 16
				
				WHEN 19 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 20 => par_add <= "00010101";
							 par_data <= "0000000001000000";--- 16
							 main_count := main_count+1;
				WHEN 21 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 22 => par_wr <="1";
							 main_count := main_count+1;		
							
				WHEN 23 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 24 => par_add <= "00010111";
							 par_data <= "0000000000000000";--- 0
							 main_count := main_count+1;
				WHEN 25 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 26 => par_wr <="1";
							 main_count := main_count+1;		
							
				--- FTW 
				WHEN 27 => par_wr <="1";
							 main_count := main_count+1;
				WHEN 28 => par_add <= "00010011";
							 par_data <= "0000000000010000";
							 main_count := main_count+1;
				WHEN 29 => par_wr <="0";
							 main_count := main_count+1;
				WHEN 30 => par_wr <="1";
							 main_count := main_count+1;		
							 
							 
							 
							 
				WHEN 31 => dds_io_update <='1';
							 main_count := main_count+1;
				WHEN 32 to 34 => main_count:=main_count+1;
				--WHEN 35 => main_count :=3;
				WHEN 35 => null;
							  
			END CASE;
		END IF;
	END PROCESS;
	
	---- write to DAC for amplitude tuning ----
	
	PROCESS (clk_in0)
		VARIABLE main_count: INTEGER range 0 to 3:=0;
		VARIABLE main_amplitude_var : STD_LOGIC_VECTOR (13 downto 0);
	BEGIN
		IF (clk_in0'event and clk_in0='0') then
			CASE main_count IS
				WHEN 0 => dac_out <= main_amplitude_var; -----set DAC amplitude
							 --dac_out <= "00000000000000";
							 dac_wr_pin <= '0';
							 main_count:=1;
				WHEN 1 => dac_wr_pin <= '1'; -------------write to dac for amplitude
				          main_count:=2;
				WHEN 2 => dac_wr_pin <= '0'; -------------write to dac for amplitude
				          main_count:=3;
--				WHEN 3 => main_count:=0;
				WHEN 3 => if (main_amplitude_var = main_amplitude) then
							   null;
							 else
								main_amplitude_var := main_amplitude;
								main_count:=0;
							end if;
			END CASE;
		END IF;
	END PROCESS;
	
	
	
	
	
	
	------- generate slower clock --------
	process (clk_in0)
		variable count: integer range 0 to 21 :=0;
	begin
		if (rising_edge(clk_in0)) then
			count := count + 1;
			if (count <= 10) then
				clk_system <= '1';
			elsif (count <= 20) then
				clk_system <= '0';
			elsif (count=21) then
				count :=0;
			end if;
		end if;
	end process;
	
	--- Write LED data to the TI converter chip --
	
	PROCESS
		VARIABLE count_serial: INTEGER RANGE 0 to 19:=0;
	BEGIN
		WAIT UNTIL (clk_system'EVENT AND clk_system='1');
		CASE count_serial IS
			WHEN 0  => LED_OE <= '0'; LED_LE <= '0'; LED_CLK <= '0';
			WHEN 1  => LED_SDI <= LED_VALUE (7 DOWNTO 7); LED_CLK <= '0';---- first----
			WHEN 2  => LED_CLK <= '1';
			WHEN 3  => LED_SDI <= LED_VALUE (6 DOWNTO 6); LED_CLK <= '0';
			WHEN 4  => LED_CLK <= '1';
			WHEN 5  => LED_SDI <= LED_VALUE (5 DOWNTO 5); LED_CLK <= '0';
			WHEN 6  => LED_CLK <= '1';
			WHEN 7  => LED_SDI <= LED_VALUE (4 DOWNTO 4); LED_CLK <= '0';
			WHEN 8  => LED_CLK <= '1';
			WHEN 9  => LED_SDI <= LED_VALUE (3 DOWNTO 3); LED_CLK <= '0';
			WHEN 10  => LED_CLK <= '1';
			WHEN 11  => LED_SDI <= LED_VALUE (2 DOWNTO 2); LED_CLK <= '0';
			WHEN 12  => LED_CLK <= '1';
			WHEN 13  => LED_SDI <= LED_VALUE (1 DOWNTO 1); LED_CLK <= '0';
			WHEN 14  => LED_CLK <= '1';
			WHEN 15  => LED_SDI <= LED_VALUE (0 DOWNTO 0); LED_CLK <= '0';---- last bit----
			WHEN 16  => LED_CLK <= '1';
			WHEN 17 => LED_OE <= '0';LED_LE <= '1';
			WHEN 18 => LED_OE <= '0';LED_LE <= '0';
			WHEN 19 => LED_OE <= '0';LED_LE <= '0';
		END CASE;
		count_serial := count_serial +1;
		IF (count_serial = 18) THEN
			count_serial :=0;	
		END IF;
	END PROCESS;


end behaviour;
