--------------------------------------------------------------------------
-- photon.vhd — XEM7305 pulse sequencer, Phase 1 scaffold
--
-- PORT MIGRATION PHASE ONLY. This instantiates the full legacy endpoint
-- map (same addresses as VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd)
-- against the new-generation okHost interface, so the host-interface
-- migration can be verified on real hardware before the RAM/FIFO/PMT
-- sequencer logic (Phases 2-5) is ported in.
--
-- Endpoints are stubbed: WireIns/TriggerIn are read into signals and
-- partially shown on LEDs; BTPipeIn writes are accepted but discarded
-- (ep_ready tied high, like the legacy design's own pipe_in_ready <= '1');
-- BTPipeOut reads return a fixed, per-endpoint test pattern so each
-- address is distinguishable when probed with FrontPanel / a Python
-- smoke test. None of this is real sequencer behavior yet.
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
-- wires/pipes. The real FIFOs ported in Phase 3 will need to widen to
-- match, which is a throughput improvement but a real interface change.
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

	-- Target interface bus (new-generation okHost)
	signal okClk      : STD_LOGIC;
	signal okHE       : STD_LOGIC_VECTOR(112 downto 0);
	signal okEH       : STD_LOGIC_VECTOR(64 downto 0);
	signal okEHx      : STD_LOGIC_VECTOR(65*7-1 downto 0); -- 7 endpoints need an okEH slot

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

	-- BTPipeIn stubs (0x80 pulse program, 0x81 DDS program) — writes accepted, discarded
	signal pipe80_ready : STD_LOGIC := '1';
	signal pipe81_ready : STD_LOGIC := '1';

	-- BTPipeOut stubs (0xA0/0xA1/0xA2) — fixed per-endpoint test pattern, always "ready"
	signal pipeA0_data  : STD_LOGIC_VECTOR(31 downto 0) := x"A0A0A0A0";
	signal pipeA1_data  : STD_LOGIC_VECTOR(31 downto 0) := x"A1A1A1A1";
	signal pipeA2_data  : STD_LOGIC_VECTOR(31 downto 0) := x"A2A2A2A2";
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

	osc_clk : IBUFGDS port map (O => sys_clk, I => sys_clkp, IB => sys_clkn);

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

	okWO : okWireOR generic map (N => 7) port map (okEH => okEH, okEHx => okEHx);

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

	-- BTPipeIn endpoints (writes accepted, contents discarded until Phase 3 wires in the real FIFOs)
	pi80 : okBTPipeIn port map (
		okHE => okHE, okEH => okEHx(3*65-1 downto 2*65), ep_addr => x"80",
		ep_write => open, ep_blockstrobe => open, ep_dataout => open, ep_ready => pipe80_ready
	);
	pi81 : okBTPipeIn port map (
		okHE => okHE, okEH => okEHx(4*65-1 downto 3*65), ep_addr => x"81",
		ep_write => open, ep_blockstrobe => open, ep_dataout => open, ep_ready => pipe81_ready
	);

	-- BTPipeOut endpoints (fixed test pattern per address until Phase 3 wires in the real FIFOs)
	poA0 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(5*65-1 downto 4*65), ep_addr => x"A0",
		ep_read => open, ep_blockstrobe => open, ep_datain => pipeA0_data, ep_ready => pipeOut_ready
	);
	poA1 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(6*65-1 downto 5*65), ep_addr => x"A1",
		ep_read => open, ep_blockstrobe => open, ep_datain => pipeA1_data, ep_ready => pipeOut_ready
	);
	poA2 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(7*65-1 downto 6*65), ep_addr => x"A2",
		ep_read => open, ep_blockstrobe => open, ep_datain => pipeA2_data, ep_ready => pipeOut_ready
	);

end arch;
