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
	signal okEHx      : STD_LOGIC_VECTOR(65*3-1 downto 0);
	
  -- Endpoint connections:
	------ configuration register ------
	signal ep00wire        : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	------ normal pmt measure period -------
	signal ep01wire        : STD_LOGIC_VECTOR(31 downto 0);
	
	------ output data to PC ------
	signal ep21wire		  : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	signal ep22wire		  : STD_LOGIC_VECTOR(31 downto 0):=x"00000000";
	------ Trigger in ------
	signal ep40wire        : STD_LOGIC_VECTOR(31 downto 0);

	----- These are for pipe logic ----
	
	signal pipe_in_write   : STD_LOGIC;
	signal pipe_in_ready   : STD_LOGIC;
	signal pipe_in_data    : STD_LOGIC_VECTOR(31 downto 0);
	
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


	
	---- fifo pulser signal ----
	
	signal   fifo_pulser_rst 		: STD_LOGIC;
	signal	fifo_pulser_rd_clk	: STD_LOGIC;
	signal	fifo_pulser_rd_en		: STD_LOGIC;
	signal	fifo_pulser_dout		: STD_LOGIC_VECTOR(63 downto 0);
	signal	fifo_pulser_full		: STD_LOGIC;
	signal	fifo_pulser_empty		: STD_LOGIC;
	signal   fifo_pulser_rd_data_count: STD_LOGIC_VECTOR(7 downto 0);
	
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
	
	signal   pulser_infinite_loop: std_logic;
	signal   pulser_start_bit: std_logic;
	signal   pulser_counter_reset: std_logic;
	signal   pulser_ram_reset: std_logic;
	
	
	--------------------aux logic for 	-----


	
begin
		clk_50 <= sys_clk;
		
PLL: pulser_PLL PORT MAP (inclk0=>sys_clk,c0=>clk_100,c1=>clk_200);

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
		

		pulser_infinite_loop <= ep00wire(1);			
		pulser_start_bit <= ep00wire(2);
		
		
		pulser_counter_reset <= ep40wire(0);
		pulser_ram_reset <= ep40wire(1);	
				
		
	
ram1: pulser_RAM port map (
		wrclock => pulser_ram_clka,
		wren => pulser_ram_wea,
		wraddress => pulser_ram_addra,
		data => pulser_ram_dina,
		rdclock => pulser_ram_clkb,
		rdaddress => pulser_ram_addrb,
		q => pulser_ram_doutb);	
		
ep21wire <= pulser_ram_doutb(63 downto 32);
ep22wire <= pulser_ram_doutb(31 downto 0);
pulser_ram_addrb <= ep01wire(9 downto 0);
pulser_ram_clkb <= okClk;
led <= pulser_ram_addrb(1 downto 0);

------------ write to ram process --------
		
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

okWO : okWireOR     generic map (N=>3) port map (okEH=>okEH, okEHx=>okEHx);

wi00 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"00", ep_dataout=>ep00wire);
wi01 : okWireIn    port map (okHE=>okHE,                                  ep_addr=>x"01", ep_dataout=>ep01wire);
ep40 : okTriggerIn  port map (okHE=>okHE,                                  ep_addr=>x"40", ep_clk=>okClk, ep_trigger=>ep40wire);
wo21 : okWireOut   port map (okHE=>okHE, okEH=>okEHx( 1*65-1 downto 0*65 ), ep_addr=>x"21", ep_datain=>ep21wire);
wo22 : okWireOut   port map (okHE=>okHE, okEH=>okEHx( 3*65-1 downto 2*65 ), ep_addr=>x"22", ep_datain=>ep22wire);
ep80 : okBTPipeIn  port map (okHE=>okHE, okEH=>okEHx( 2*65-1 downto 1*65 ), ep_addr=>x"80", 
                             ep_write=>pipe_in_write, ep_blockstrobe=>bs_in, ep_dataout=>pipe_in_data, ep_ready=>pipe_in_ready);
end arch;