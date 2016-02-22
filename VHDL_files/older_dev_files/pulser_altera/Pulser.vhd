---------------
--- Pulser ----
---------------

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.std_logic_arith.all;
use IEEE.std_logic_misc.all;
use IEEE.std_logic_unsigned.all;

use work.FRONTPANEL.all;
use work.all;

entity Pulser is
	port (
		okUH      : in     STD_LOGIC_VECTOR(4 downto 0);
		okHU      : out    STD_LOGIC_VECTOR(2 downto 0);
		okUHU     : inout  STD_LOGIC_VECTOR(31 downto 0);
		okAA      : inout  STD_LOGIC;

		sys_clk   : in     STD_LOGIC; ---- 50 MHz input clock
		
		---- Puler pins connection ----
		dds_bus_out	:out		std_LOGIC_VECTOR(31 downto 0);
		dds_bus_in	:in 		std_logic_vector(7 downto 0);
		ttl_out		:out		std_logic_vector(35 downto 0);
		aux_clk_in	:in		std_logic;
		aux_io		:out		std_LOGIC_VECTOR(17 downto 0);
		pmt_in		:in		std_logic;
		trigger_in	:in		std_logic;
		aux_in		:in		std_logic;
		
		
		---- LED on the module ---
		led       : out    STD_LOGIC_VECTOR(1 downto 0);
		---- LED on the breakout board ----
		led_array : out    STD_LOGIC_VECTOR(7 downto 0)
	);
end Pulser;

architecture arch of Pulser is
	signal okClk      : STD_LOGIC;
	signal okHE       : STD_LOGIC_VECTOR(112 downto 0);
	signal okEH       : STD_LOGIC_VECTOR(64 downto 0);
	signal okEHx      : STD_LOGIC_VECTOR(65*7-1 downto 0);
	
  -- Endpoint connections:
	------ configuration register ------
	signal ep00wire        : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	------ normal pmt measure period -------
	signal ep01wire        : STD_LOGIC_VECTOR(31 downto 0);
	
	------ Manual overwrite of the output logic ------
	------ Because there are 4 possible states for each channel of the logic out (there are
	------ always on, always off, follow pulse, follow pulse with inverted), we need 2 bits of
	------ information to store.
	
	signal ep02wire		  : STD_LOGIC_VECTOR(31 downto 0);
	signal ep03wire		  : STD_LOGIC_VECTOR(31 downto 0);
	------ DDS channel ---------------------
	signal ep04wire		  : STD_LOGIC_VECTOR(31 downto 0);
	------ Number of loops wanted in the infinite loop ---------------------
	signal ep05wire		  : STD_LOGIC_VECTOR(31 downto 0);
	------ number of us delay in the line triggering ---------------------
	signal ep06wire		  : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	
	------ output data to PC ------
	signal ep21wire		  : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	signal ep22wire		  : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	------ Trigger in ------
	signal ep40wire        : STD_LOGIC_VECTOR(31 downto 0);

	----- These are for pipe logic ----
	
	signal pipe_in_write   : STD_LOGIC;
	signal pipe_in_ready   : STD_LOGIC;
	signal pipe_in_data    : STD_LOGIC_VECTOR(31 downto 0);
	
	signal pipe_in_write_dds   : STD_LOGIC;
	signal pipe_in_ready_dds   : STD_LOGIC;
	signal pipe_in_data_dds    : STD_LOGIC_VECTOR(31 downto 0);
	
	signal time_resolved_pipe_out_read   : STD_LOGIC;
	signal time_resolved_pipe_out_valid  : STD_LOGIC;
	signal time_resolved_pipe_out_data   : STD_LOGIC_VECTOR(31 downto 0);
	
	signal normal_pmt_pipe_out_read   : STD_LOGIC;
	signal normal_pmt_pipe_out_valid  : STD_LOGIC;
	signal normal_pmt_pipe_out_data   : STD_LOGIC_VECTOR(31 downto 0);
	
	
	
	signal bs_in, bs_out   : STD_LOGIC;
	signal bs_in_dds, bs_out_dds   : STD_LOGIC;
	
	--- CLOCKs -----

	--- clk 100 MHz from PLL.
	signal clk_100         : STD_LOGIC;
	--- clk 200 MHz from PLL to sample the input PMT signal. Any slower clock will miss the pulse ---
	signal clk_200         : STD_LOGIC;
	--- clk 50 MHz directly connected to the input clock from the OK module
	signal clk_50          : STD_LOGIC; 
	--- slow clock at 1 MHz self-generated ---
	signal clk_1			  : STD_LOGIC;

	---- fifo photon signal ----
	
	signal   fifo_photon_rst 		: STD_LOGIC;
	signal	fifo_photon_wr_clk	: STD_LOGIC;
	signal	fifo_photon_din		: STD_LOGIC_VECTOR(31 downto 0);
	signal	fifo_photon_wr_en		: STD_LOGIC;
	signal	fifo_photon_full		: STD_LOGIC;
	signal	fifo_photon_empty		: STD_LOGIC;
	signal   fifo_photon_rd_data_count: STD_LOGIC_VECTOR(15 downto 0);
	signal   photon_time_tag      : STD_LOGIC_VECTOR(31 downto 0);
	
	---- fifo pulser signal ----
	
	signal   fifo_pulser_rst 		: STD_LOGIC;
	signal	fifo_pulser_rd_clk	: STD_LOGIC;
	signal	fifo_pulser_rd_en		: STD_LOGIC;
	signal	fifo_pulser_dout		: STD_LOGIC_VECTOR(63 downto 0);
	signal	fifo_pulser_full		: STD_LOGIC;
	signal	fifo_pulser_empty		: STD_LOGIC;
	signal   fifo_pulser_rd_data_count: STD_LOGIC_VECTOR(7 downto 0);
	
		---- dds pulser signal ----
	
	signal   fifo_dds_rst 		: STD_LOGIC;
	signal	fifo_dds_rd_clk	: STD_LOGIC;
	signal   fifo_dds_rd_clk_temp: STD_LOGIC;
	signal	fifo_dds_rd_en		: STD_LOGIC;
	signal	fifo_dds_dout		: STD_LOGIC_VECTOR(15 downto 0);
	signal	fifo_dds_full		: STD_LOGIC;
	signal	fifo_dds_empty		: STD_LOGIC;
	signal	fifo_dds_wr_data_count		: STD_LOGIC_vector(10 downto 0);
	signal   dds_ram_reset     : STD_LOGIC;
	
	----- main signal route -----
	signal 	master_counter_hi_bit: STD_LOGIC_VECTOR (29 downto 0); ---- this one is the counter for the pulser
	signal 	master_counter_low_bit: STD_LOGIC_VECTOR (1 downto 0); ---- this one is the sub counter for the photon data. The combined is 32 bit
	----- These two are the time variable of the evolution of the pulses.
	----- Due to the limitation of the integer size in VHDL, the number has to
	----- be divided into two separated numbers.
	signal 	master_counter_hi_int: integer range 0 to 1073741824 := 0;
	signal	master_counter_low_int: integer range 0 to 3 := 0;
	
	----- logic signal ------------------------------
	----- This is the channels for the pulse sequence
	
	signal 	master_logic			:STD_LOGIC_VECTOR (31 downto 0);
	
	----- pmt signal --------------------------------------------

	signal 	pmt_synced				: STD_LOGIC; ------------
	
	----- pulser ram ------
	
	signal	pulser_ram_clka        		: STD_LOGIC;
	signal	pulser_ram_wea 				: STD_LOGIC;
	signal	pulser_ram_addra 				: STD_LOGIC_VECTOR(9 DOWNTO 0);
	signal	pulser_ram_dina 				: STD_LOGIC_VECTOR(63 DOWNTO 0);
	signal	pulser_ram_clkb 				: STD_LOGIC;
	signal	pulser_ram_addrb 				: STD_LOGIC_VECTOR(9 DOWNTO 0);
	signal	pulser_ram_doutb 				: STD_LOGIC_VECTOR(63 DOWNTO 0);
	
	------ This is the total number of sequence completed in the infinite loop mode of the pulser
	signal   seq_count_bit					: STD_LOGIC_VECTOR(15 downto 0);
	
	----- various flag -----
	signal   pulser_counter_reset			: STD_LOGIC; ----'0' = reset. '1' = run
	signal   pulser_ram_reset			   : STD_LOGIC; ----'1' = reset pulser ram. '0' = normal operating state
	signal	pulser_infinite_loop			: STD_LOGIC; ----'1' = infinite loop. '0' = single shot
	signal	pulser_start_bit				: STD_LOGIC; ----'1' = run sequence. '0' = pause sequence
	signal	pulser_sequence_done			: STD_LOGIC; ----'1' = sequence is done. '0' = seq is not yet done. In infinite mode it will always be '0'
	signal	pulser_flag_register			: STD_LOGIC_VECTOR (15 downto 0);---- this vector is to combine all above for convenience.
	
	--====== NORMAL PMT ========--
	-- FIFO --
	signal   normal_pmt_rd_data_count: STD_LOGIC_VECTOR (10 DOWNTO 0);
	signal   normal_pmt_full: STD_LOGIC;
	signal   normal_pmt_fifo_reset: STD_LOGIC;
	signal   normal_pmt_fifo_data: STD_LOGIC_VECTOR (31 DOWNTO 0);
	signal   normal_pmt_empty: STD_LOGIC;
	signal   normal_pmt_wr_clk: STD_LOGIC:='0';
	signal   normal_pmt_wr_en: STD_LOGIC:='0';
	signal   normal_pmt_block_aval: STD_LOGIC:= '0';
	
	-- auto mode parameter --
	signal   normal_pmt_count_period : INTEGER RANGE 0 TO 65535:=1000; --- normal pmt period in ms ---
	signal   normal_pmt_auto_count_clk : STD_LOGIC:='0';
	signal   normal_pmt_count_trigger : STD_LOGIC := '0';
	
	-- PMT data --
	signal   pmt_count: INTEGER RANGE 0 TO 2147483647:=0;
	signal   pmt_count_reset: STD_LOGIC;
	signal   pmt_sampled: STD_LOGIC;
	
	--====== READOUT PMT ========--
	--FIFO--
	signal   readout_count_rd_data_count: STD_LOGIC_VECTOR (10 DOWNTO 0);
	signal   readout_pmt_full: STD_LOGIC;
	signal   readout_count_fifo_reset: STD_LOGIC;
	signal   readout_count_fifo_data: STD_LOGIC_VECTOR (31 DOWNTO 0);
	signal   readout_pmt_empty: STD_LOGIC;
	signal   readout_count_wr_clk: STD_LOGIC:='0';
	signal   readout_count_wr_en: STD_LOGIC:='0';
	signal   readout_count_pipe_out_read: STD_LOGIC := '0';
	signal   readout_count_pipe_out_valid: STD_LOGIC;
	signal   readout_count_pipe_out_data: STD_LOGIC_VECTOR (31 DOWNTO 0);
	--DATA--
	signal	pmt_readout_count: INTEGER RANGE 0 TO 2147483647:=0;
	signal	readout_should_count : STD_LOGIC := '0';
	
	
	----- line triggering -----
	signal line_triggering_enabled: STD_LOGIC := '0'; ----- 1 means trigger with line
	signal line_triggering_pulse: STD_LOGIC := '0'; ------ line triggering pulse from some input
	signal line_triggering_conditioned: STD_LOGIC:= '0'; ----- conditioning of the 60 hz input
	
	--------------------aux logic for 	-----


	
begin
---- Use Megafunction to generate 100 MHz (ch1) and 200 MHz (ch2) from the 50 MHz input clock
		clk_50 <= sys_clk;
PLL: pulser_PLL PORT MAP (inclk0=>sys_clk,c0=>clk_100,c1=>clk_200);
		--clk_100<=okClk;
---- fifo to store data from the pc before writing to the block ram for pulser ---
fifo2: pulser_FIFO port map(
		aclr=>fifo_pulser_rst,
		wrclk=>okClk,
		rdclk=>fifo_pulser_rd_clk,
		data=> pipe_in_data,
		wrreq=> pipe_in_write,
		rdreq=> fifo_pulser_rd_en, 
		q=> fifo_pulser_dout,
		wrfull=> fifo_pulser_full,
		rdempty=> fifo_pulser_empty,
		rdusedw=>fifo_pulser_rd_data_count);
		
		pipe_in_ready <= '1';
		fifo_pulser_rst <= '0';
		
		---- test sandbox ----
--		led_array <= pulser_ram_doutb(7 downto 0) WHEN ep00wire(18 downto 16) = "000" ELSE
--		             pulser_ram_doutb(15 downto 8) WHEN ep00wire(18 downto 16) = "001" ELSE
--					    pulser_ram_doutb(23 downto 16) WHEN ep00wire(18 downto 16) = "010" ELSE
--					    pulser_ram_doutb(31 downto 24) WHEN ep00wire(18 downto 16) = "011" ELSE
--						 pulser_ram_doutb(39 downto 32) WHEN ep00wire(18 downto 16) = "100" ELSE
--		             pulser_ram_doutb(47 downto 40) WHEN ep00wire(18 downto 16) = "101" ELSE
--					    pulser_ram_doutb(55 downto 48) WHEN ep00wire(18 downto 16) = "110" ELSE
--					    pulser_ram_doutb(63 downto 56);
--					    	 
--		pulser_ram_clkb <= okClk;
--		pulser_ram_addrb <= ep00wire(9 downto 0);
		--led_array(7 downto 4) <= master_logic(3 downto 0);
		--led_array <= master_logic(7 downto 0);
		--led_array <= pulser_ram_addrb(7 downto 0);
		pulser_infinite_loop <= ep00wire(1);			
		pulser_start_bit <= ep00wire(2);
		led(0) <= ep00wire(1);	
		led(1) <= ep00wire(2);
		--led_array(2) <= ep00wire(3);
		--pulser_ram_reset<='0';
		--led_array(3) <= clk_100;
		
		
--------- DDS fifo --------------
fifo4: dds_fifo port map(
		wrclk=>okClk,
		rdclk=>fifo_dds_rd_clk,
		data=> pipe_in_data_dds,
		wrreq=> pipe_in_write_dds,
		rdreq=> fifo_dds_rd_en, 
		q=> fifo_dds_dout,
		wrfull=> fifo_dds_full,
		rdempty=> fifo_dds_empty,
		wrusedw=>fifo_dds_wr_data_count,
		aclr=>fifo_dds_rst);
		
		
		---- DDS stuff ----
		fifo_dds_rd_clk_temp <= not dds_bus_in(1);
		fifo_dds_rd_en <= not dds_bus_in(0);
		dds_bus_out(15 downto 0) <= not fifo_dds_dout;
		dds_bus_out(27) <= not fifo_dds_empty;
		dds_bus_out(24) <= not ep40wire(6); ------------reset dds chip ----
		dds_bus_out(26) <= not (master_logic(19) or ep40wire(4)); -----------dds reset----------
		dds_bus_out(25) <= not (master_logic(18) or ep40wire(5)); ---- step to next value
		dds_bus_out(31 downto 28) <= not ep04wire(3 downto 0); ---- address of the dds
		fifo_dds_rst <= ep40wire(7); -------- this fifo never gets reset because if there's anything in the fifo, it will get written into the ram right away
		pipe_in_ready_dds <= '1'; ---- enable pipe in. The only pipe in used in this design is writing of the pulse into this fifo.
		--led_array<=fifo_dds_wr_data_count(7 downto 0);
		led_array<=master_logic(7 downto 0);
		
		pulser_counter_reset <= ep40wire(0);
		pulser_ram_reset <= ep40wire(1);	
		
---------------------------------------------------------
---------- condition read clk ---------------------------
---------------------------------------------------------

	process(clk_50, fifo_dds_rd_clk_temp)
	begin
		if (rising_edge(clk_50)) then
			if (fifo_dds_rd_clk_temp = '1') then
				fifo_dds_rd_clk <= '1';
			else
				fifo_dds_rd_clk <= '0';
			end if;
		end if;
	end process;

------- generate slow clock at 1 MHz ------

	process (clk_50)
		variable count: integer range 0 to 51 :=0;
	begin
		if (rising_edge(clk_50)) then
			count := count + 1;
			if (count <= 25) then
				clk_1 <= '1';
			elsif (count <= 50) then
				clk_1 <= '0';
			elsif (count=51) then
				count :=0;
			end if;
		end if;
	end process;		
		
	
ram1: pulser_RAM port map (
		wrclock => pulser_ram_clka,
		wren => pulser_ram_wea,
		wraddress => pulser_ram_addra,
		data => pulser_ram_dina,
		rdclock => pulser_ram_clkb,
		rdaddress => pulser_ram_addrb,
		q => pulser_ram_doutb);	
		
	process (clk_100,pulser_ram_reset)
		variable write_ram_address: integer range 0 to 1023:=0;
		variable ram_process_count: integer range 0 to 8:=0;
	begin
		----- reset ram -----
		----- This doesn't really reset the ram but only put the address to zero so that the next writing 
		----- from the fifo to the ram will start from the first address. Since each pulse will end with all zeros anyway
		----- it's ok to have old information in the ram. The execution will never get past the end line.
		if (pulser_ram_reset = '1') then
			write_ram_address := 0;
			ram_process_count := 0;
		elsif rising_edge(clk_100) then
			case ram_process_count is
				--------- first two prepare and check whether there is anything in the fifo. This can be done by looking at the pin
				--------- fifo_pulser empty. 
				when 0 => fifo_pulser_rd_clk <='1';
							 fifo_pulser_rd_en <= '0';
							 pulser_ram_wea <='0';
							 ram_process_count := 1;
				when 1 => fifo_pulser_rd_clk <='0';
							 if (fifo_pulser_empty = '1') then ---- '1' is empty. Go back to case 0 
								ram_process_count:=0; 
							 else 
								ram_process_count := 2;  ---- if there's anything in the fifo, go to the next case
							 end if;
				-------- there's sth in the fifo ---------
				when 2 => fifo_pulser_rd_en <= '1';
							 ram_process_count:=3;
				when 3 => fifo_pulser_rd_clk <= '1'; ------------- read from fifo --------------
							 pulser_ram_wea <='1';
							 pulser_ram_clka <= '0';
							 ram_process_count:=4;
				when 4 => fifo_pulser_rd_clk <= '0';
							 ram_process_count:=5;
				
				---------- prepare data and address that are about to be written to the ram------
				
				when 5 => pulser_ram_addra <= CONV_STD_LOGIC_VECTOR(write_ram_address,10);
							 pulser_ram_dina <= fifo_pulser_dout;
							 ram_process_count:=6;
				when 6 => pulser_ram_clka <= '1'; ----------write to ram
							 ram_process_count:=7;
				when 7 => write_ram_address:=write_ram_address+1; ----- increase address by one
							 ram_process_count:=8;
				----- check again if the fifo is empty or not. Basically this whole process will
				----- keep writing to ram until fifo is empty.
				when 8 => if (fifo_pulser_empty = '1') then 
								ram_process_count:=0;
							 else 
								ram_process_count:=2; 
							 end if;
			end case;
		end if;
	end process;
	
------------------------------- pulser module -------------------------------
----- There is a main counter that go through each step in the RAM data. -----
----- The array of data of 64 bit has two portion. Time stamp and logic. -----
----- The convention is to specify which state of the logic at each time stamp
----- The first time stamp doesn't do anything. And the pulse will stop until
----- the end line is reached. The endline is specified from timestamp = 0. ---
----- The logic in the endline also doesn't do anything.----------------------


	process (clk_100, pulser_counter_reset)
		variable seq_count: INTEGER range 0 to 65535;--- count number of seq run
		variable count1: INTEGER range 0 to 3:=0;
		variable time_count: INTEGER:=0;
		variable time_stamp: INTEGER:=0;
		variable ram_read_address: integer range 0 to 1023:=0;
		variable ram_process_count: INTEGER range 0 to 10:=0;
		variable ram_data_out_1: STD_LOGIC_VECTOR (63 downto 0);
		variable ram_data_out_2: STD_LOGIC_VECTOR (63 downto 0);
	begin
		IF (pulser_counter_reset = '1') then
			ram_process_count:=0;
			ram_read_address:=0;
			count1:=0;
			time_count:=0;
			time_stamp:=0;
			master_logic <= "00000000000000000000000000000000";
			pulser_sequence_done <= '0';----------------"seq done flag" is deasserted
			seq_count:=0;

		ELSIF (rising_edge(clk_100)) THEN
			IF (pulser_start_bit = '1') THEN ------ This means the "run" flaged is set such that the pulse runs.
			CASE ram_process_count IS
			
				------------- read initial configuration --------------
				when 0 =>   ram_read_address:=0;
							   -----------wait for line triggering--------
--								IF ((ep00wire(3) = '1' and line_triggering_pulse = '1') or (ep00wire(3) = '0')) then
--									ram_process_count := ram_process_count + 1;
--								END IF;

								ram_process_count := ram_process_count + 1;

								
				WHEN 1 =>   pulser_ram_clkb <= '1';
								ram_process_count := ram_process_count + 1;		
								

				WHEN 2 =>   master_logic <= pulser_ram_doutb (31 downto 0);
							   ram_read_address:=1;
							   pulser_ram_clkb <= '0';
							   ram_process_count := ram_process_count + 1;
				WHEN 3 =>   pulser_ram_clkb <= '1';
								ram_process_count := ram_process_count + 1;
				WHEN 4 => 	ram_data_out_2:=pulser_ram_doutb;
								time_stamp := CONV_INTEGER(UNSIGNED (ram_data_out_2(61 downto 32)));
								
								ram_read_address := 2;
								ram_process_count := ram_process_count + 1;
								
				---- read process -----		 
				WHEN 5 => IF (time_count+1 = time_stamp) THEN ----------- approaching the time stamp
								IF (count1 = 0) THEN
									pulser_ram_clkb <= '0';
									count1 :=1;	
								ELSIF (count1 = 1) THEN
									pulser_ram_clkb <= '1'; -----------ram data is read
									count1 :=2;
								ELSIF (count1 = 2) THEN
									pulser_ram_clkb <= '0';
									ram_data_out_1 := ram_data_out_2;
									ram_data_out_2 := pulser_ram_doutb; -----------latch output from ram to ram_data_out
									count1:=3;
								ELSIF (count1 = 3) THEN
									count1:=0;
									time_count := time_count+1;
									ram_read_address := ram_read_address+1;
									time_stamp := CONV_INTEGER(UNSIGNED (ram_data_out_2(61 downto 32)));
										IF (time_stamp = 0) THEN ----------- if the end line (specified by timestamp = 0) is reached.
											IF (pulser_infinite_loop = '1') then ---- if it's in the infinite looped mode then jump back to the beginning
												ram_process_count:=0;
												ram_read_address:=0;
												count1:=0;
												time_count:=0;
												time_stamp:=0;
												master_logic <= ram_data_out_1(31 downto 0);
												seq_count:=seq_count+1;-------- increase number of sequence count --------
												if (CONV_INTEGER(UNSIGNED (ep05wire(15 downto 0))) /= 0) then
													if (seq_count = CONV_INTEGER(UNSIGNED (ep05wire(15 downto 0)))) then
														master_logic <= "00000000000000000000000000000000";
														ram_process_count := 6;
													end if;
												end if;
											else
												-------------- one shot mode, after this go to limbo -------
												master_logic <= "00000000000000000000000000000000";
												ram_process_count := ram_process_count+1;
									
												
											end if;
										ELSE
											master_logic <= ram_data_out_1(31 downto 0);
										END IF;
								END IF;
							 ELSE
							 
								----------- if the time stamp is not yet reached, keeps counting -------
								IF (count1 = 0) THEN
									count1 :=1;
								ELSIF (count1 = 1) THEN
									count1 :=2;
								ELSIF (count1 = 2) THEN
									count1:=3;
								ELSIF (count1 = 3) THEN
									count1:=0;
									time_count := time_count+1;
								END IF;
							 END IF;
				------- this is limbo, you can't escape from here. To get out you need to reset the pulser. -----
				WHEN 6 => pulser_sequence_done <= '1';
				WHEN OTHERS => NULL;
				
			END CASE;
			END IF;
			------ link the read address to the ram address in the process
			pulser_ram_addrb<=conv_std_logic_vector(ram_read_address,10);
			------ get timestamp data ready. This is to be used to tag photon in the time resolved photon process ----
			photon_time_tag(31 downto 2) <= CONV_STD_LOGIC_VECTOR(time_count,30);
			photon_time_tag(1 downto 0) <= CONV_STD_LOGIC_VECTOR(count1,2);
			------ The number of sequence looped------------------------
			seq_count_bit <= CONV_STD_LOGIC_VECTOR(seq_count,16);
			
			--led_array<=CONV_STD_LOGIC_VECTOR(time_count,30)(29 downto 22);
			
		END IF;
		
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

okWO : okWireOR     generic map (N=>7) port map (okEH=>okEH, okEHx=>okEHx);

wi00 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"00", ep_dataout=>ep00wire);
wi01 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"01", ep_dataout=>ep01wire);
wi02 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"02", ep_dataout=>ep02wire);
wi03 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"03", ep_dataout=>ep03wire);
wi04 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"04", ep_dataout=>ep04wire);
wi05 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"05", ep_dataout=>ep05wire);
wi06 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"06", ep_dataout=>ep06wire);
ep40 : okTriggerIn  port map (okHE=>okHE,                                  ep_addr=>x"40", ep_clk=>clk_1, ep_trigger=>ep40wire);
wo21 : okWireOut   port map (okHE=>okHE, okEH=>okEHx( 1*65-1 downto 0*65 ), ep_addr=>x"21", ep_datain=>ep21wire);
wo22 : okWireOut   port map (okHE=>okHE, okEH=>okEHx( 4*65-1 downto 3*65 ), ep_addr=>x"22", ep_datain=>ep22wire);
ep80 : okBTPipeIn  port map (okHE=>okHE, okEH=>okEHx( 2*65-1 downto 1*65 ), ep_addr=>x"80", 
                             ep_write=>pipe_in_write, ep_blockstrobe=>bs_in, ep_dataout=>pipe_in_data, ep_ready=>pipe_in_ready);
--ep81 : okBTPipeIn  port map (okHE=>okHE, okEH=>okEHx( 6*65-1 downto 5*65 ), ep_addr=>x"81", 
--                             ep_write=>pipe_in_write_dds, ep_blockstrobe=>bs_in_dds, ep_dataout=>pipe_in_data_dds, ep_ready=>pipe_in_ready_dds);
ep81 : okPipeIn  port map (okHE=>okHE, okEH=>okEHx( 6*65-1 downto 5*65 ), ep_addr=>x"81", 
                             ep_write=>pipe_in_write_dds, ep_dataout=>pipe_in_data_dds);
----time resolved----
epA0 : okBTPipeOut port map (okHE=>okHE, okEH=>okEHx( 3*65-1 downto 2*65 ), ep_addr=>x"A0", 
                             ep_read=>time_resolved_pipe_out_read, ep_blockstrobe=>bs_out, ep_datain=>time_resolved_pipe_out_data, ep_ready=>time_resolved_pipe_out_valid);
----normal pmt ----
epA1 : okBTPipeOut port map (okHE=>okHE, okEH=>okEHx( 5*65-1 downto 4*65 ), ep_addr=>x"A1", 
                             ep_read=>normal_pmt_pipe_out_read, ep_blockstrobe=>bs_out, ep_datain=>normal_pmt_pipe_out_data, ep_ready=>normal_pmt_pipe_out_valid);
----readout pmt ----
epA2 : okBTPipeOut port map (okHE=>okHE, okEH=>okEHx( 7*65-1 downto 6*65 ), ep_addr=>x"A2", 
                             ep_read=>readout_count_pipe_out_read, ep_blockstrobe=>bs_out, ep_datain=>readout_count_pipe_out_data, ep_ready=>readout_count_pipe_out_valid);

end arch;