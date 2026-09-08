--------------------------------------------------------------------------
-- photon.vhd — XEM7305 pulse sequencer, Phase 1 + Phase 2 + Phase 3 scaffold
--
-- PORT MIGRATION PHASES ONLY. This instantiates the full legacy endpoint
-- map (same addresses as VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd)
-- against the new-generation okHost interface, the new clocking tree
-- (Phase 2), and the RAM/FIFO IP for the pulse-sequence memory and
-- photon/readout counters (Phase 3), so all three can be verified on
-- real hardware before the actual PMT/DDS sequencer state machines
-- (Phase 5) are ported in.
--
-- Phase 3 note: dds_fifo is deliberately NOT included here. In the
-- legacy design its read clock is supplied by the DDS board itself
-- (dds_logic_fifo_rd_clk), not one of our internal clocks -- so it
-- belongs with the rest of the DDS I/O in Phase 4/5, which is already
-- blocked on a breakout board/pinout for the XEM7305.
--
-- Phase 3 also only wires up the RAM *write* path (BTPipeIn 0x80 ->
-- pulse_fifo -> pulser_ram, via a minimal auto-incrementing-address
-- drain process below) and the three read FIFOs' *read* side
-- (pulser_ram/fifo_photon/normal_pmt_fifo/readout_count_fifo ->
-- BTPipeOut). Nothing yet drives pulser_ram's read port or the three
-- read FIFOs' write ports -- that requires the real PMT-counting and
-- sequencer state machines, which are Phase 5. Until then, BTPipeOut
-- 0xA0/0xA1/0xA2 will simply read back empty (their FIFOs are real,
-- but never written to).
--
-- WireIns/TriggerIn are read into signals and partially shown on LEDs.
-- BTPipeIn 0x80 and BTPipeOut 0xA0/0xA1/0xA2 now reach real FIFO/RAM IP
-- (Phase 3); BTPipeIn 0x81 still discards writes (ep_ready tied high,
-- like the legacy design's own pipe_in_ready <= '1'). None of this is
-- real sequencer/PMT behavior yet -- that's Phase 5.
--
-- Endpoint map (unchanged from the legacy XEM6010 design, so
-- Python_files/servers/pulser/api.py needs no address changes):
--   0x00-0x06  WireIn   (mode/config, PMT period, manual overrides, DDS
--                        channel select, loop count, line-trigger delay)
--   0x40       TriggerIn (reset counters/RAM/FIFOs, advance/reset DDS)
--   0x21,0x22  WireOut  (status flags, photon-FIFO count)
--   0x80       BTPipeIn  (pulse sequence program)
--   0x81       BTPipeIn  (DDS program)
--   0xA0       BTPipeOut (time-resolved photon counts)
--   0xA1       BTPipeOut (normal PMT counts)
--   0xA2       BTPipeOut (readout counts)
--
-- Note: on this newer FrontPanel generation, wire/pipe data is 32 bits
-- wide (okWireIn/okBTPipeIn/... ep_dataout/ep_datain are all
-- std_logic_vector(31 downto 0)) instead of the legacy design's 16-bit
-- wires/pipes. Phase 3's FIFOs are sized natively for this width (see
-- below) instead of replicating the legacy 16-bit-wide interface.
--
-- Phase 2 adds the clocking tree: a Clocking Wizard (MMCM) IP
-- (src/ip/clk_wiz_0) replaces the legacy design's clk_pll_100_in_200_out,
-- producing the same three clocks (clk_200, clk_100, clk_20) used by
-- later phases (PMT oversampling / main sequencer state machine /
-- DDS+line-trigger), but from the XEM7305's 200 MHz sys_clk instead of
-- the XEM6010's 100 MHz Cypress clock. Endpoints 0x23-0x26 are
-- bring-up-only additions (no legacy equivalent) so this phase can be
-- verified from Python without an oscilloscope: 0x23 reports MMCM lock
-- status, 0x24-0x26 are free-running counters on clk_200/clk_100/clk_20
-- whose count rate a host script can measure against a wall-clock delay
-- to confirm each clock's actual frequency.
--
-- Phase 3 adds bring-up-only status endpoints 0x27-0x2A (no legacy
-- equivalent), each reporting one FIFO's read-side occupancy
-- (rd_data_count) so a host script can watch data move through the
-- pulse-sequence RAM path and confirm the three counting FIFOs are
-- reachable, without needing real PMT/DDS hardware.
--------------------------------------------------------------------------

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.std_logic_arith.all;
use IEEE.std_logic_unsigned.all;
use work.FRONTPANEL.all;

library UNISIM;
use UNISIM.vcomponents.all;

entity photon is
	port (
		okUH      : in     STD_LOGIC_VECTOR(4 downto 0);
		okHU      : out    STD_LOGIC_VECTOR(3 downto 0);
		okRSVD    : in     STD_LOGIC_VECTOR(3 downto 0);
		okUHU     : inout  STD_LOGIC_VECTOR(31 downto 0);
		okAA      : inout  STD_LOGIC;

		sys_clkp  : in     STD_LOGIC;
		sys_clkn  : in     STD_LOGIC;

		led       : out    STD_LOGIC_VECTOR(3 downto 0)
	);
end photon;

architecture arch of photon is
	signal sys_clk    : STD_LOGIC;

	-- Phase 2 clocking tree (see src/ip/clk_wiz_0), replacing the legacy
	-- clk_pll_100_in_200_out. Component/port names match Vivado's
	-- standard Clocking Wizard wrapper; confirm against the generated
	-- src/ip/clk_wiz_0/clk_wiz_0.vhd after running create_project.tcl.
	component clk_wiz_0 port (
		clk_in1  : in  STD_LOGIC;
		clk_out1 : out STD_LOGIC; -- 200 MHz, PMT oversampling (Phase 5)
		clk_out2 : out STD_LOGIC; -- 100 MHz, main sequencer state machine
		clk_out3 : out STD_LOGIC; -- 20 MHz, DDS FIFO / line-trigger logic
		locked   : out STD_LOGIC
	);
	end component;

	signal clk_200    : STD_LOGIC;
	signal clk_100    : STD_LOGIC;
	signal clk_20     : STD_LOGIC;
	signal clk_locked : STD_LOGIC;

	-- Phase 3 RAM/FIFO IP (see src/ip/pulse_fifo, pulser_ram, fifo_photon,
	-- normal_pmt_fifo, readout_count_fifo). Depths/widths sized from the
	-- legacy design's ipcore_dir/*.xco files, adapted to this generation's
	-- native 32-bit pipe width (see README). Component/port names match
	-- Vivado's standard FIFO Generator / Block Memory Generator wrappers;
	-- confirm against the actual generated .vhd files once built.
	--
	-- pulse_fifo: 32-bit write (BTPipeIn 0x80) -> 64-bit read (feeds
	-- pulser_ram, kept 64-bit so Phase 5's sequencer can reuse the
	-- legacy 64-bit instruction word format unchanged).
	component pulse_fifo port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(31 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(63 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(7 downto 0) -- 256-deep (64-bit words)
	);
	end component;

	-- pulser_ram: Simple Dual-Port RAM (write-only port A, read-only port
	-- B), matching the legacy design exactly (memory_type=Simple_Dual_Port_RAM
	-- in ipcore_dir/pulser_ram.xco) -- not a true dual-port RAM.
	component pulser_ram port (
		clka  : in  STD_LOGIC;
		wea   : in  STD_LOGIC_VECTOR(0 downto 0);
		addra : in  STD_LOGIC_VECTOR(9 downto 0);
		dina  : in  STD_LOGIC_VECTOR(63 downto 0);
		clkb  : in  STD_LOGIC;
		addrb : in  STD_LOGIC_VECTOR(9 downto 0);
		doutb : out STD_LOGIC_VECTOR(63 downto 0)
	);
	end component;

	-- fifo_photon: native 32-bit both sides (BTPipeOut 0xA0), no width
	-- conversion needed now that the pipe itself is 32 bits wide.
	component fifo_photon port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(31 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(31 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(14 downto 0) -- 32768-deep
	);
	end component;

	-- normal_pmt_fifo: native 32-bit both sides (BTPipeOut 0xA1).
	component normal_pmt_fifo port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(31 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(31 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(9 downto 0) -- 1024-deep
	);
	end component;

	-- readout_count_fifo: native 32-bit both sides (BTPipeOut 0xA2).
	component readout_count_fifo port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(31 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(31 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(9 downto 0) -- 1024-deep
	);
	end component;

	-- Free-running counters, one per new clock domain, so a host script
	-- can measure actual frequency (count delta / wall-clock delta)
	-- instead of trusting the MMCM configuration blindly.
	signal cnt_200 : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal cnt_100 : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal cnt_20  : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');

	-- WireOut endpoints (0x23-0x26) — Phase 2 bring-up only, no legacy
	-- equivalent; see file header comment.
	signal ep23wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep24wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep25wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep26wire : STD_LOGIC_VECTOR(31 downto 0);

	-- WireOut endpoints (0x27-0x2A) — Phase 3 bring-up only, no legacy
	-- equivalent; see file header comment.
	signal ep27wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep28wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep29wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep2Awire : STD_LOGIC_VECTOR(31 downto 0);

	-- pulse_fifo (BTPipeIn 0x80 write side, feeds pulser_ram)
	signal fifo_pulser_din  : STD_LOGIC_VECTOR(31 downto 0);
	signal fifo_pulser_wr_en : STD_LOGIC;
	signal fifo_pulser_rd_en : STD_LOGIC;
	signal fifo_pulser_dout  : STD_LOGIC_VECTOR(63 downto 0);
	signal fifo_pulser_full  : STD_LOGIC;
	signal fifo_pulser_empty : STD_LOGIC;
	signal fifo_pulser_rd_data_count : STD_LOGIC_VECTOR(7 downto 0);

	-- pulser_ram (write port A driven by the drain process below; read
	-- port B not yet driven by anything -- that's Phase 5's sequencer)
	signal pulser_ram_wea   : STD_LOGIC_VECTOR(0 downto 0) := "0";
	signal pulser_ram_addra : STD_LOGIC_VECTOR(9 downto 0) := (others => '0');
	signal pulser_ram_dina  : STD_LOGIC_VECTOR(63 downto 0);
	signal pulser_ram_addrb : STD_LOGIC_VECTOR(9 downto 0) := (others => '0');
	signal pulser_ram_doutb : STD_LOGIC_VECTOR(63 downto 0);

	-- Phase 3 bring-up only: drains pulse_fifo into pulser_ram at an
	-- auto-incrementing address (wraps at the RAM's 1024-word depth).
	-- NOT the real sequencer -- just proves BTPipeIn 0x80 -> pulse_fifo
	-- -> pulser_ram works end-to-end. Real address/replay/loop-count
	-- logic is Phase 5.
	signal ram_write_addr  : STD_LOGIC_VECTOR(9 downto 0) := (others => '0');
	signal ram_write_state : INTEGER range 0 to 2 := 0;

	-- fifo_photon (BTPipeOut 0xA0 read side; write side unconnected
	-- until Phase 5's PMT time-tagging logic exists)
	signal fifo_photon_wr_en : STD_LOGIC := '0';
	signal fifo_photon_din   : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal fifo_photon_rd_en : STD_LOGIC;
	signal fifo_photon_dout  : STD_LOGIC_VECTOR(31 downto 0);
	signal fifo_photon_full  : STD_LOGIC;
	signal fifo_photon_empty : STD_LOGIC;
	signal fifo_photon_rd_data_count : STD_LOGIC_VECTOR(14 downto 0);
	signal fifo_photon_rst  : STD_LOGIC;

	-- normal_pmt_fifo (BTPipeOut 0xA1 read side; write side unconnected
	-- until Phase 5's PMT counting logic exists)
	signal normal_pmt_fifo_wr_en : STD_LOGIC := '0';
	signal normal_pmt_fifo_din   : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal normal_pmt_fifo_rd_en : STD_LOGIC;
	signal normal_pmt_fifo_dout  : STD_LOGIC_VECTOR(31 downto 0);
	signal normal_pmt_fifo_full  : STD_LOGIC;
	signal normal_pmt_fifo_empty : STD_LOGIC;
	signal normal_pmt_fifo_rd_data_count : STD_LOGIC_VECTOR(9 downto 0);
	signal normal_pmt_fifo_reset : STD_LOGIC;

	-- readout_count_fifo (BTPipeOut 0xA2 read side; write side
	-- unconnected until Phase 5's readout-counting logic exists)
	signal readout_count_fifo_wr_en : STD_LOGIC := '0';
	signal readout_count_fifo_din   : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal readout_count_fifo_rd_en : STD_LOGIC;
	signal readout_count_fifo_dout  : STD_LOGIC_VECTOR(31 downto 0);
	signal readout_count_fifo_full  : STD_LOGIC;
	signal readout_count_fifo_empty : STD_LOGIC;
	signal readout_count_fifo_rd_data_count : STD_LOGIC_VECTOR(9 downto 0);
	signal readout_count_fifo_reset : STD_LOGIC;

	-- Target interface bus (new-generation okHost)
	signal okClk      : STD_LOGIC;
	signal okHE       : STD_LOGIC_VECTOR(112 downto 0);
	signal okEH       : STD_LOGIC_VECTOR(64 downto 0);
	signal okEHx      : STD_LOGIC_VECTOR(65*15-1 downto 0); -- 15 endpoints need an okEH slot

	-- WireIn endpoints (0x00-0x06) — same addresses/roles as the legacy design
	signal ep00wire   : STD_LOGIC_VECTOR(31 downto 0); -- mode/config flags
	signal ep01wire   : STD_LOGIC_VECTOR(31 downto 0); -- normal PMT measure period
	signal ep02wire   : STD_LOGIC_VECTOR(31 downto 0); -- manual override select
	signal ep03wire   : STD_LOGIC_VECTOR(31 downto 0); -- manual override state/invert
	signal ep04wire   : STD_LOGIC_VECTOR(31 downto 0); -- DDS channel select
	signal ep05wire   : STD_LOGIC_VECTOR(31 downto 0); -- infinite-loop repeat count
	signal ep06wire   : STD_LOGIC_VECTOR(31 downto 0); -- line-trigger delay (us)

	-- TriggerIn endpoint (0x40)
	signal ep40wire   : STD_LOGIC_VECTOR(31 downto 0);

	-- WireOut endpoints (0x21, 0x22)
	signal ep21wire   : STD_LOGIC_VECTOR(31 downto 0);
	signal ep22wire   : STD_LOGIC_VECTOR(31 downto 0);

	-- BTPipeIn 0x80 (pulse program) now writes into pulse_fifo (Phase 3,
	-- see below); 0x81 (DDS program) remains a stub until Phase 4/5.
	signal pipe80_ready : STD_LOGIC := '1';
	signal pipe81_ready : STD_LOGIC := '1';

	-- BTPipeOut 0xA0/0xA1/0xA2 now read from real FIFOs (Phase 3); always
	-- "ready" like the legacy design's own pipe_out_valid signals, so the
	-- host is expected to check the 0x28/0x29/0x2A occupancy WireOuts
	-- before reading rather than rely on ep_ready reflecting real data.
	signal pipeOut_ready : STD_LOGIC := '1';

	-- sys_clk heartbeat, proves the onboard oscillator/IBUFGDS path independently
	-- of the USB-driven LEDs below
	signal heartbeat_div : STD_LOGIC_VECTOR(23 downto 0) := (others => '0');
begin

	------------------------------------------------------------------
	-- LEDs: bits 0-2 mirror WireIn 0x00, so writing that wire from the
	-- host is visible immediately. Bit 3 blinks off sys_clk to confirm
	-- the onboard oscillator independently of USB traffic.
	------------------------------------------------------------------
	led(0) <= '0' when ep00wire(0) = '1' else 'Z';
	led(1) <= '0' when ep00wire(1) = '1' else 'Z';
	led(2) <= '0' when ep00wire(2) = '1' else 'Z';
	led(3) <= '0' when heartbeat_div(23) = '1' else 'Z';

	process (sys_clk)
	begin
		if rising_edge(sys_clk) then
			heartbeat_div <= heartbeat_div + 1;
		end if;
	end process;

	------------------------------------------------------------------
	-- WireOut test content (0x21/0x22): echo something derived from the
	-- WireIn/Trigger state so a host-side read can confirm round-trip
	-- communication.
	------------------------------------------------------------------
	ep21wire <= ep00wire;
	ep22wire <= ep40wire;

	------------------------------------------------------------------
	-- Phase 2 clocking bring-up (0x23-0x26): MMCM lock status plus one
	-- free-running counter per new clock domain, each wrapping every
	-- ~2^32 cycles (~21.5s at 200 MHz, up to ~3.6min at 20 MHz) — ample
	-- headroom for a short host-side measurement window.
	------------------------------------------------------------------
	ep23wire <= (0 => clk_locked, others => '0');
	ep24wire <= cnt_200;
	ep25wire <= cnt_100;
	ep26wire <= cnt_20;

	process (clk_200)
	begin
		if rising_edge(clk_200) then
			cnt_200 <= cnt_200 + 1;
		end if;
	end process;

	process (clk_100)
	begin
		if rising_edge(clk_100) then
			cnt_100 <= cnt_100 + 1;
		end if;
	end process;

	process (clk_20)
	begin
		if rising_edge(clk_20) then
			cnt_20 <= cnt_20 + 1;
		end if;
	end process;

	------------------------------------------------------------------
	-- Phase 3 RAM/FIFO bring-up (0x27-0x2A): read-side occupancy of
	-- each FIFO, so a host script can watch data move through the
	-- pulse-sequence RAM path without needing real PMT/DDS hardware.
	------------------------------------------------------------------
	ep27wire <= (31 downto 8  => '0') & fifo_pulser_rd_data_count;
	ep28wire <= (31 downto 15 => '0') & fifo_photon_rd_data_count;
	ep29wire <= (31 downto 10 => '0') & normal_pmt_fifo_rd_data_count;
	ep2Awire <= (31 downto 10 => '0') & readout_count_fifo_rd_data_count;

	-- Reset wiring preserved from the legacy design (same ep40wire bit
	-- roles), even though nothing yet consumes fifo_photon/normal_pmt_fifo/
	-- readout_count_fifo's write side -- keeps these triggers meaningful
	-- once Phase 5 lands instead of silently doing nothing until then.
	fifo_photon_rst          <= ep40wire(3);
	normal_pmt_fifo_reset    <= ep40wire(2);
	readout_count_fifo_reset <= ep40wire(4);

	-- Phase 3 bring-up only: drains pulse_fifo into pulser_ram at an
	-- auto-incrementing address. pulse_fifo is First-Word-Fall-Through,
	-- so dout is already valid whenever empty='0' -- no extra wait state
	-- needed before latching it. ep40wire(1) resets the write address,
	-- matching the legacy design's pulser_ram_reset bit.
	process (clk_100)
	begin
		if rising_edge(clk_100) then
			fifo_pulser_rd_en <= '0';
			pulser_ram_wea    <= "0";
			if ep40wire(1) = '1' then
				ram_write_addr  <= (others => '0');
				ram_write_state <= 0;
			else
				case ram_write_state is
					when 0 =>
						if fifo_pulser_empty = '0' then
							pulser_ram_dina   <= fifo_pulser_dout;
							pulser_ram_addra  <= ram_write_addr;
							fifo_pulser_rd_en <= '1';
							ram_write_state   <= 1;
						end if;
					when 1 =>
						pulser_ram_wea  <= "1";
						ram_write_state <= 2;
					when 2 =>
						ram_write_addr  <= ram_write_addr + 1;
						ram_write_state <= 0;
				end case;
			end if;
		end if;
	end process;

	osc_clk : IBUFGDS port map (O => sys_clk, I => sys_clkp, IB => sys_clkn);

	clk_gen : clk_wiz_0 port map (
		clk_in1  => sys_clk,
		clk_out1 => clk_200,
		clk_out2 => clk_100,
		clk_out3 => clk_20,
		locked   => clk_locked
	);

	-- Instantiate the okHost and connect endpoints
	okHI : okHost port map (
		okUH   => okUH,
		okHU   => okHU,
		okUHU  => okUHU,
		okAA   => okAA,
		okRSVD => okRSVD,
		okClk  => okClk,
		okHE   => okHE,
		okEH   => okEH
	);

	okWO : okWireOR generic map (N => 15) port map (okEH => okEH, okEHx => okEHx);

	-- WireIn endpoints
	wi00 : okWireIn port map (okHE => okHE, ep_addr => x"00", ep_dataout => ep00wire);
	wi01 : okWireIn port map (okHE => okHE, ep_addr => x"01", ep_dataout => ep01wire);
	wi02 : okWireIn port map (okHE => okHE, ep_addr => x"02", ep_dataout => ep02wire);
	wi03 : okWireIn port map (okHE => okHE, ep_addr => x"03", ep_dataout => ep03wire);
	wi04 : okWireIn port map (okHE => okHE, ep_addr => x"04", ep_dataout => ep04wire);
	wi05 : okWireIn port map (okHE => okHE, ep_addr => x"05", ep_dataout => ep05wire);
	wi06 : okWireIn port map (okHE => okHE, ep_addr => x"06", ep_dataout => ep06wire);

	-- TriggerIn endpoint
	tr40 : okTriggerIn port map (okHE => okHE, ep_addr => x"40", ep_clk => sys_clk, ep_trigger => ep40wire);

	-- WireOut endpoints
	wo21 : okWireOut port map (okHE => okHE, okEH => okEHx(1*65-1 downto 0*65), ep_addr => x"21", ep_datain => ep21wire);
	wo22 : okWireOut port map (okHE => okHE, okEH => okEHx(2*65-1 downto 1*65), ep_addr => x"22", ep_datain => ep22wire);

	-- BTPipeIn endpoints. 0x80 (Phase 3) writes into pulse_fifo; 0x81
	-- (DDS program) stays a discard-everything stub until Phase 4/5.
	pi80 : okBTPipeIn port map (
		okHE => okHE, okEH => okEHx(3*65-1 downto 2*65), ep_addr => x"80",
		ep_write => fifo_pulser_wr_en, ep_blockstrobe => open, ep_dataout => fifo_pulser_din, ep_ready => pipe80_ready
	);
	pi81 : okBTPipeIn port map (
		okHE => okHE, okEH => okEHx(4*65-1 downto 3*65), ep_addr => x"81",
		ep_write => open, ep_blockstrobe => open, ep_dataout => open, ep_ready => pipe81_ready
	);

	-- BTPipeOut endpoints (Phase 3): each now reads from a real FIFO
	-- instead of a fixed test pattern. All three read empty until
	-- Phase 5 drives their write side -- see file header comment.
	poA0 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(5*65-1 downto 4*65), ep_addr => x"A0",
		ep_read => fifo_photon_rd_en, ep_blockstrobe => open, ep_datain => fifo_photon_dout, ep_ready => pipeOut_ready
	);
	poA1 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(6*65-1 downto 5*65), ep_addr => x"A1",
		ep_read => normal_pmt_fifo_rd_en, ep_blockstrobe => open, ep_datain => normal_pmt_fifo_dout, ep_ready => pipeOut_ready
	);
	poA2 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(7*65-1 downto 6*65), ep_addr => x"A2",
		ep_read => readout_count_fifo_rd_en, ep_blockstrobe => open, ep_datain => readout_count_fifo_dout, ep_ready => pipeOut_ready
	);

	-- WireOut endpoints (Phase 2 clocking bring-up, see file header comment)
	wo23 : okWireOut port map (okHE => okHE, okEH => okEHx(8*65-1 downto 7*65), ep_addr => x"23", ep_datain => ep23wire);
	wo24 : okWireOut port map (okHE => okHE, okEH => okEHx(9*65-1 downto 8*65), ep_addr => x"24", ep_datain => ep24wire);
	wo25 : okWireOut port map (okHE => okHE, okEH => okEHx(10*65-1 downto 9*65), ep_addr => x"25", ep_datain => ep25wire);
	wo26 : okWireOut port map (okHE => okHE, okEH => okEHx(11*65-1 downto 10*65), ep_addr => x"26", ep_datain => ep26wire);

	-- WireOut endpoints (Phase 3 RAM/FIFO bring-up, see file header comment)
	wo27 : okWireOut port map (okHE => okHE, okEH => okEHx(12*65-1 downto 11*65), ep_addr => x"27", ep_datain => ep27wire);
	wo28 : okWireOut port map (okHE => okHE, okEH => okEHx(13*65-1 downto 12*65), ep_addr => x"28", ep_datain => ep28wire);
	wo29 : okWireOut port map (okHE => okHE, okEH => okEHx(14*65-1 downto 13*65), ep_addr => x"29", ep_datain => ep29wire);
	wo2A : okWireOut port map (okHE => okHE, okEH => okEHx(15*65-1 downto 14*65), ep_addr => x"2A", ep_datain => ep2Awire);

	-- Phase 3 RAM/FIFO IP instantiations
	pulse_fifo_inst : pulse_fifo port map (
		rst    => '0', -- matches legacy: never reset, drains into RAM right away
		wr_clk => okClk,
		rd_clk => clk_100,
		din    => fifo_pulser_din,
		wr_en  => fifo_pulser_wr_en,
		rd_en  => fifo_pulser_rd_en,
		dout   => fifo_pulser_dout,
		full   => fifo_pulser_full,
		empty  => fifo_pulser_empty,
		rd_data_count => fifo_pulser_rd_data_count
	);

	pulser_ram_inst : pulser_ram port map (
		clka  => clk_100,
		wea   => pulser_ram_wea,
		addra => pulser_ram_addra,
		dina  => pulser_ram_dina,
		clkb  => clk_100,
		addrb => pulser_ram_addrb,
		doutb => pulser_ram_doutb
	);

	fifo_photon_inst : fifo_photon port map (
		rst    => fifo_photon_rst,
		wr_clk => clk_200,
		rd_clk => okClk,
		din    => fifo_photon_din,
		wr_en  => fifo_photon_wr_en,
		rd_en  => fifo_photon_rd_en,
		dout   => fifo_photon_dout,
		full   => fifo_photon_full,
		empty  => fifo_photon_empty,
		rd_data_count => fifo_photon_rd_data_count
	);

	normal_pmt_fifo_inst : normal_pmt_fifo port map (
		rst    => normal_pmt_fifo_reset,
		wr_clk => clk_100,
		rd_clk => okClk,
		din    => normal_pmt_fifo_din,
		wr_en  => normal_pmt_fifo_wr_en,
		rd_en  => normal_pmt_fifo_rd_en,
		dout   => normal_pmt_fifo_dout,
		full   => normal_pmt_fifo_full,
		empty  => normal_pmt_fifo_empty,
		rd_data_count => normal_pmt_fifo_rd_data_count
	);

	readout_count_fifo_inst : readout_count_fifo port map (
		rst    => readout_count_fifo_reset,
		wr_clk => clk_100,
		rd_clk => okClk,
		din    => readout_count_fifo_din,
		wr_en  => readout_count_fifo_wr_en,
		rd_en  => readout_count_fifo_rd_en,
		dout   => readout_count_fifo_dout,
		full   => readout_count_fifo_full,
		empty  => readout_count_fifo_empty,
		rd_data_count => readout_count_fifo_rd_data_count
	);

end arch;
