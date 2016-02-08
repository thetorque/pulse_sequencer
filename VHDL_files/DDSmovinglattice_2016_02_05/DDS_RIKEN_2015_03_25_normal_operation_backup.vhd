
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
	 
	 -- pulser bus --
	 dds_bus_in: in std_LOGIC_vector(31 downto 0);
	 dds_bus_out: out std_LOGIC_vector(7 downto 0);
	 tx_enable: out std_LOGIC_vector(1 downto 0);
	 
	 
	 -- DAC control pin --
	 
	 dac_out : out std_LOGIC_VECTOR (13 downto 0);
	 dac_wr_pin: out std_logic;
	 
	 
	 ----address set pins----
	 add_in: in std_logic_vector (3 downto 0) -- set address of the DDS board (4bit)
    );

end DDS_RIKEN;

architecture behaviour of DDS_RIKEN is
	---- various constants ----
	constant CRF2_modulus: std_LOGIC_vector(15 downto 0) := "0000000010001001";
	constant CRF2_profile: std_LOGIC_vector(15 downto 0) := "0000000010000000";
	constant CRF2_address: std_LOGIC_vector(7 downto 0) := "00000111";
	
	constant CRF1_address: std_LOGIC_vector(7 downto 0) :="00000001";
	constant CRF1_enable_amp_scale: std_LOGIC_vector(15 downto 0) := "0000000100001000";
	constant CRF1_disable_amp_scale: std_LOGIC_vector(15 downto 0) := "0000000000001000";

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
	signal main_frequency: std_LOGIC_vector(63 downto 0);
	
	--- signal for bus talking to the pulser ----
	signal bus_in_address: std_LOGIC_vector(3 downto 0);
	signal bus_in_fifo_rd_clk: std_logic;
	signal bus_in_fifo_rd_en: std_logic;
	signal bus_in_fifo_empty: std_logic;
	signal bus_in_ram_reset: std_logic;
	signal bus_in_step_to_next_value: std_logic;
	signal bus_in_reset_dds_chip: std_logic;
	
	signal reset_fpga: std_logic;
	
	---- fifo reading from pulser
	signal   fifo_dds_dout			: STD_LOGIC_VECTOR (15 downto 0);
	signal 	fifo_dds_empty			: STD_LOGIC;
	signal	fifo_dds_rd_clk      : STD_LOGIC;
	signal	fifo_dds_rd_en			: STD_LOGIC;
	
	---- ram stuff
	signal	dds_ram_data_in		: STD_LOGIC_VECTOR (15 DOWNTO 0);
	signal	dds_ram_rdaddress		: STD_LOGIC_VECTOR (11 DOWNTO 0);
	signal	dds_ram_rdclock		: STD_LOGIC;
	signal	dds_ram_wraddress		: STD_LOGIC_VECTOR (14 DOWNTO 0);
	signal	dds_ram_wrclock		: STD_LOGIC := '1';
	signal	dds_ram_wren		   : STD_LOGIC;
	signal	dds_ram_data_out		: STD_LOGIC_VECTOR (127 DOWNTO 0);
	signal 	dds_ram_reset        : STD_LOGIC;
	signal   dds_step_to_next_freq : STD_LOGIC;
	signal 	dds_step_to_next_freq_sampled: STD_LOGIC;
	
	signal clk_50: std_logic;


begin
	pll: dds_pll port map (inclk0=>clk_dds, c0=>clk_50);
	--- test pulse bus ---
--	led_value <= main_frequency (7 downto 0) WHEN add_in = "0001" ELSE
--					main_frequency (15 downto 8) WHEN add_in = "0010" ELSE
--					main_frequency (23 downto 16) WHEN add_in = "0100" ELSE
--					main_frequency (31 downto 24) WHEN add_in = "1000" ELSE
--					x"88";
--   led_value <=main_frequency (31 downto 24);
	--led_value <= dds_bus_in (7 downto 0);
	--led_value <= dds_bus_in (15 downto 8);
	--led_value <= dds_bus_in (23 downto 16);
	--led_value <= dds_bus_in (31 downto 24);
	
	
	--- assignment of dds bus in to various pins ---
	bus_in_address <= dds_bus_in(31 downto 28);
	bus_in_fifo_empty <= dds_bus_in(27);
	bus_in_ram_reset <= dds_bus_in(26);
	bus_in_step_to_next_value <= dds_bus_in(25);
	bus_in_reset_dds_chip <= dds_bus_in(24);
	dds_bus_out(0) <= bus_in_fifo_rd_en;
	dds_bus_out(1) <= bus_in_fifo_rd_clk;
	
	bus_in_fifo_rd_clk<=fifo_dds_rd_clk WHEN bus_in_address = add_in(3 downto 0) else 'Z';
	bus_in_fifo_rd_en<=fifo_dds_rd_en WHEN bus_in_address = add_in(3 downto 0) else 'Z';
	tx_enable <= "11" WHEN bus_in_address = add_in(3 downto 0) else "00";
	reset_fpga<=bus_in_reset_dds_chip;
	fifo_dds_dout <= dds_bus_in(15 downto 0);
	fifo_dds_empty <= bus_in_fifo_empty;
	dds_ram_rdclock<=clk_50;
	dds_ram_reset<=bus_in_ram_reset;
	dds_step_to_next_freq<=bus_in_step_to_next_value;
	
	led_VALUE (2 downto 0) <= dds_ram_rdaddress(2 downto 0);
	led_VALUE (7 downto 4) <= bus_in_address;
	led_VALUE (3) <= bus_in_fifo_empty;
--	led_value <= dds_ram_data_out(23 downto 16);
	
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
	
	--main_amplitude <= "11000000000000"; --dds_ram_data_out(31 downto 18);
	main_amplitude <= dds_ram_data_out(31 downto 18);
	main_frequency <= dds_ram_data_out(127 downto 64);
	--main_frequency <= x"0a3d70a3d70a3d7f";
	--main_frequency <= x"0a3d70a480000000";
	
	par_16_bit <= "1";
	--dds_master_reset <= '0';
	ps <= "000"; --- select profile 0
	par_rd <= "0";
	
	ram1: dds_ram port map (data=>dds_ram_data_in,
									rdaddress=>dds_ram_rdaddress, 
									rdclock=>dds_ram_rdclock, 
									wraddress=>dds_ram_wraddress, 
									wrclock=>dds_ram_wrclock,
									wren=>dds_ram_wren,
									q=>dds_ram_data_out);
									
	dds_step_to_next_freq_sampled <= dds_step_to_next_freq;
	
	process (dds_step_to_next_freq_sampled, dds_ram_reset)
		variable dds_step_count: integer range 0 to 4095:=0;
	begin
			if (dds_ram_reset = '1') then
				dds_step_count:=0;
			elsif (rising_edge(dds_step_to_next_freq_sampled)) then	
				dds_step_count := dds_step_count+1;
			end if;
			dds_ram_rdaddress<=CONV_STD_LOGIC_VECTOR(dds_step_count,12);
	end process;
	
	---- read from pulser and write to RAM ---
	process (clk_system,dds_ram_reset)
		variable write_ram_address: integer range 0 to 32767:=0;
		variable ram_process_count: integer range 0 to 9:=0;
	begin
		----- reset ram -----
		----- This doesn't really reset the ram but only put the address to zero so that the next writing 
		----- from the fifo to the ram will start from the first address. Since each pulse will end with all zeros anyway
		----- it's ok to have old information in the ram. The execution will never get past the end line.
		if (dds_ram_reset = '1') then
			write_ram_address := 0;
			ram_process_count := 0;
		elsif rising_edge(clk_system) then
			case ram_process_count is
				--------- first two prepare and check whether there is anything in the fifo. This can be done by looking at the pin
				--------- fifo_pulser empty. 
				when 0 => fifo_dds_rd_clk <='1';
							 fifo_dds_rd_en <= '0';
							 dds_ram_wren <='0';
							 ram_process_count := 1;

				when 1 => fifo_dds_rd_clk <='0';
							 ram_process_count := 2;

				when 2 => if (bus_in_address = add_in(3 downto 0)) then
								if (fifo_dds_empty = '1') then ---- '1' is empty. Go back to case 0 
									ram_process_count:=0; 
								else 
									ram_process_count := 3; --2 ---- if there's anything in the fifo, go to the next case
								end if;
							 else 
								ram_process_count:=0;
							 end if;

				-------- there's sth in the fifo ---------
				when 3 => fifo_dds_rd_en <= '1';
							 ram_process_count:=4;
				when 4 => fifo_dds_rd_clk <= '1'; ------------- read from fifo --------------
							 dds_ram_wren <='1';
							 dds_ram_wrclock <= '1';
							 ram_process_count:=5;
				when 5 => fifo_dds_rd_clk <= '0';
							 ram_process_count:=6;
				
				---------- prepare data and address that are about to be written to the ram------
				
				when 6 => dds_ram_wraddress <= CONV_STD_LOGIC_VECTOR(write_ram_address,15);
							 dds_ram_data_in <= fifo_dds_dout;
							 ram_process_count:=7;

				when 7 => dds_ram_wrclock <= '0'; ----------write to ram
							 ram_process_count:=8;
				when 8 => write_ram_address:=write_ram_address+1; ----- increase address by one
							 ram_process_count:=9;
				----- check again if the fifo is empty or not. Basically this whole process will
				----- keep writing to ram until fifo is empty.
				when 9 => if (fifo_dds_empty = '1') then 
								ram_process_count:=0;
							 else 
								ram_process_count:=3; 
							 end if;
			end case;
			--led_value<=conV_STD_LOGIC_VECTOR(write_ram_address,12)(7 downto 0);
		end if;
	end process;
	
	---- write instruction to DDS ---
	PROCESS (clk_50, reset_fpga)
		variable main_count: integer range 0 to 17:=0;
		variable sub_count: integer range 0 to 3:=0;
		variable main_frequency_var: std_LOGIC_VECTOR (63 downto 0);
		variable count_delay: integer range 0 to 65535:=0;
		variable main_amplitude_var: std_logic_vector(13 downto 0); 
		--variable main_phase_var
	BEGIN
		IF (reset_fpga = '1') then
			main_count := 0;
			count_delay :=0;
			dds_master_reset <= '1';	
		ELSIF (clk_50'event and clk_50='0') then
			CASE main_count IS
				---- initialization. DDS chip reset ----
				WHEN 0 => dds_io_update <= '0';
				          dds_master_reset <='0';
							 main_count := main_count+1;
				WHEN 1 => dds_io_update <= '0';
				          dds_master_reset <='1';
							 main_count := main_count+1;
				WHEN 2 => dds_io_update <= '0';
				          dds_master_reset <='0';
							 main_count := main_count+1;
							 
				---- DAC calibration -----
				WHEN 3 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"0F"; --- address for initial DAC calibration ---
									          par_data <=x"0105";
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;	
				
				----- delay -- wait 1 ms for DAC calibration to finish ----
				WHEN 4 => if (count_delay = 50000) then 
								main_count := main_count+1;
								count_delay := 0;
							 else
							   count_delay := count_delay +1;
							 end if;
				---- clear DAC calibration ----

				WHEN 5 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"0F"; --- address for initial DAC calibration ---
									          par_data <=x"0005";
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;	
				
				
							 
				---- set up modlus mode ---- 
							 
				WHEN 6 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=CRF2_address;
									          par_data <=CRF2_modulus;
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;	
								
				----- enable amplitude tuning ---
				
				WHEN 7 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=CRF1_address;
									          par_data <=CRF1_enable_amp_scale;
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
				
							 
				---- B -> 2^32 - 1 ---- fixed ----
					
				WHEN 8 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"15";
									          --par_data <=x"FFFF";
												 par_data <=x"0000";
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;							

				WHEN 9 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"17";
									          --par_data <=x"FFFF";
												 par_data <=x"8000";
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
							 
							 
				-------- program A modulus mode testing

				---- A --> 1	 
				WHEN 10 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"19";---0x19
									          par_data <=main_frequency_var(16 downto 1);---
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
								
				WHEN 11 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"1B";---0x1B
												 par_data(15) <='0';
									          par_data(14 downto 0) <=main_frequency_var(31 downto 17);---
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
								
				----- set frequency tuning word ----
				
				WHEN 12 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"11";
									          par_data <=main_frequency_var(47 downto 32);---
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
								
				WHEN 13 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <=x"13";
									          par_data <=main_frequency_var(63 downto 48);---
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;
								
				----- set amplitude -----
								
				WHEN 14 => CASE sub_count IS
									WHEN 0 => par_wr <= "1";
												 sub_count:=sub_count+1;
									WHEN 1 => par_add <="00110011";
												 if (main_amplitude_var = "00000000000000") then
														par_data <= x"0000";
												 else
														par_data <= x"0FFF";
												 end if;
												 sub_count:=sub_count+1;
									WHEN 2 => par_wr <= "0";
									          sub_count:=sub_count+1;
									WHEN 3 => par_wr <= "1";
												 sub_count:=0;
												 main_count:=main_count+1;
								END CASE;



							 
--				----- enable amplitude tuning ----
--				
--				WHEN 16 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 17 => par_add <= CRF1_address;
--							 par_data <= CRF1_disable_amp_scale;--- CRF1 -- enable OSK (8), 0x08 default value
--							 main_count := main_count+1;
--				WHEN 18 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 19 => par_wr <="1";
--							 main_count := main_count+1;
							 
							 
							 
							 
--				----- Profile 0 frequency ---- all 32 bits -----			 
--				WHEN 20 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 21 => par_add <= x"2F";
--							 par_data <= main_frequency_var(31 downto 16);
--							 main_count := main_count+1;
--				WHEN 22 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 23 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 24 => par_add <= x"2D";
--							 par_data <= main_frequency_var(15 downto 0);
--							 main_count := main_count+1;
--				WHEN 25 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 26 => par_wr <="1";
--							 main_count := main_count+1;
							 
--				----- amlitude scaling			 
--							 
--				WHEN 7 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 8 => par_add <= "00110011";
--							 --par_data <= "0000111111111111";
--							 par_data <= x"0FFF";
--							 main_count := main_count+1;
--				WHEN 9 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 10 => par_wr <="1";
--							 main_count := main_count+1;
		
							 
							 

--							 
	
--							
--				--- FTW 
--				WHEN 35 => par_wr <="1";
--							 main_count := main_count+1;
--				WHEN 36 => par_add <= "00010011";
--							 par_data <= "0000000000010000";
--							 main_count := main_count+1;
--				WHEN 37 => par_wr <="0";
--							 main_count := main_count+1;
--				WHEN 38 => par_wr <="1";
--							 main_count := main_count+1;	
							 
							 
							 
							 
				
				WHEN 15 => dds_io_update <='0';
							 main_count := main_count+1;				
				WHEN 16 => dds_io_update <='1';
							 main_count := main_count+1;
				WHEN 17 => if (main_frequency_var = main_frequency) then
									if (main_amplitude_var = main_amplitude) then
										null;
									else
										main_amplitude_var:=main_amplitude;
										main_count:=14;
									end if;
								else
									main_frequency_var:=main_frequency;
									main_amplitude_var:=main_amplitude;
									main_count:=10;
								end if;
			end case;
		END IF;
	END PROCESS;
	
	---- write to DAC for amplitude tuning ----
	
	PROCESS (clk_50)
		VARIABLE main_count: INTEGER range 0 to 3:=0;
		VARIABLE main_amplitude_var : STD_LOGIC_VECTOR (13 downto 0);
	BEGIN
		IF (clk_50'event and clk_50='0') then
			CASE main_count IS
				WHEN 0 => dac_out <= main_amplitude_var; -----set DAC amplitude
							 dac_wr_pin <= '0';
							 main_count:=1;
				WHEN 1 => dac_wr_pin <= '1'; -------------write to dac for amplitude
				          main_count:=2;
				WHEN 2 => dac_wr_pin <= '0'; -------------write to dac for amplitude
				          main_count:=3;
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
	process (clk_50)
		variable count: integer range 0 to 21 :=0;
	begin
		if (rising_edge(clk_50)) then
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
