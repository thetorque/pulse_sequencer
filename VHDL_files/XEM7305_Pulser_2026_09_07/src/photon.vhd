---------------------------------------------------------------------------
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
-- DDS+line-trigger). Originally sourced from the XEM7305's 200 MHz
-- sys_clk directly (via IBUFGDS); as of Phase 6a it's re-sourced from
-- MIG's ui_clk instead -- see that paragraph below. Endpoints 0x23-0x26 are
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
--
-- Phase 5a adds the real pulse-sequence FSM: it reads pulser_ram's
-- read port (unused since Phase 3), applies each 64-bit RAM word's
-- low 32 bits to master_logic for the duration given by its high 30
-- bits (a time_stamp = 0 word ends the sequence), and derives
-- logic_out from master_logic through the same per-channel
-- force/invert override mux (ep02wire/ep03wire) as the legacy
-- design. logic_out is a full 32-bit internal signal, but only its
-- low 6 bits have physical pins so far, on led_ext (a separate add-on
-- LED header, not more onboard LEDs -- see the entity port comment);
-- the rest still has no pins to go to until Phase 4's breakout board.
-- The full 32-bit value is also exposed on a new bring-up-only
-- WireOut (0x2B) for host-side verification, alongside
-- sequence-done/loop-count status (0x2C).
--
-- Phase 6a adds the DDR3 SDRAM controller (src/ip/ddr3_256_16, Xilinx
-- MIG 7-series) as pure bring-up: instantiated and clocked, but its
-- app_* command interface is tied inert (app_en/app_wdf_wren='0',
-- app_cmd="000") since nothing reads/writes it yet -- that's Phase
-- 6b's read-prefetch-buffer/write-burst-assembler adapters. MIG now
-- owns the physical sys_clk_p/sys_clk_n differential pins directly
-- (System Clock = Differential, matching the proven
-- Locally_compiled_ramtester reference exactly -- see AR#45588 on why
-- a separate IBUFGDS + MIG System Clock = No Buffer couldn't be
-- validated instead), so the old sys_clk/IBUFGDS path is gone;
-- clk_wiz_0 (Phase 2) is re-sourced from MIG's ui_clk (~81.25 MHz,
-- see create_project.tcl) instead of raw sys_clk, and both the
-- heartbeat counter and TriggerIn 0x40's ep_clk move to ui_clk too --
-- it's now the earliest clock in the whole chain that's independent
-- of USB traffic (available once just MIG's own PLL locks, without
-- needing full DDR3 calibration or clk_wiz_0's own lock). MIG's
-- sys_rst is a single-okClk-cycle active-high pulse generated at
-- configuration time (>=5 ns per UG586), same approach as ramtester's
-- own rst_cnt logic. WireOut 0x2D is a new bring-up-only addition
-- exposing init_calib_complete (bit 0) for host-side polling, since
-- nothing else surfaces DDR3 calibration status yet.
--
-- Phase 6b adds the DDR3 write/read adapters as a standalone,
-- host-driven bring-up test -- pulser_ram/the sequencer FSM aren't
-- touched yet (that's Phase 6c). The existing bring-up-only RAM-writer
-- drain process (BTPipeIn 0x80 -> pulse_fifo) now feeds ddr3_write_fifo
-- in lockstep with pulser_ram, so the same host write already exercised
-- by Phase 5a's tests also exercises the DDR3 write path. A
-- write-assembler (ui_clk domain) pairs two ddr3_write_fifo words into
-- one 128-bit MIG write burst; a read-prefetch (also ui_clk) issues
-- MIG read commands and splits the returned data back into 64-bit
-- words feeding ddr3_read_fifo, exposed on a new bring-up-only
-- BTPipeOut (0xA3) for host-side readback. Since MIG's app_addr/app_cmd
-- command channel is shared between reads and writes, the two are
-- time-multiplexed via a new host-controlled mode bit (ep00wire(4): 0
-- = write mode, 1 = read mode) rather than a runtime arbiter -- the
-- host must confirm the write path is idle (WireOut 0x2E bit 5) before
-- switching to read mode, or an in-flight write command gets abandoned
-- mid-transaction -- and symmetrically, must confirm the read path is
-- idle (WireOut 0x2F bit 16) before switching back to write mode, or a
-- read command that's already been accepted by MIG (address advanced,
-- but app_rd_data_valid not yet seen) never gets captured, and
-- resuming read mode later would deadlock forever waiting for a valid
-- pulse MIG will never reassert. New TriggerIn bit ep40wire(5) resets
-- both the write-assembler's and read-prefetch's address counters
-- back to 0. New WireIn 0x07 sets read-prefetch's per-batch read-
-- command budget (see rd_pf_issued/rd_pf_target declaration comment),
-- letting multiple write/read batches share one reset epoch (and
-- therefore walk further into DDR3's address space across a soak
-- test) without rd_pf_addr desyncing from wr_asm_addr. New WireIn bit
-- ep00wire(6) (ddr3_read_fifo_rst) clears the read FIFO and read-
-- prefetch state per batch, WITHOUT touching the addresses, so each
-- batch reads from a clean read-side state (like batch 0) instead of
-- relying on a fragile inter-batch FIFO carryover that raced across
-- the ui_clk->okClk crossing -- see its declaration comment.
-- ddr3_read_fifo is natively asymmetric (64-bit write / 32-bit read)
-- so BTPipeOut 0xA3 wires directly to it, no intermediary logic --
-- a symmetric-FIFO-plus-hand-rolled-splitter version broke
-- okBTPipeOut's internal timing assumptions and produced a
-- duplicated/shifted readback on real hardware (see its component
-- declaration comment). This reintroduces a "which 32-bit half comes
-- out first" question the same way pulse_fifo's write-side word order
-- once did -- resolved empirically by test/ddr3_roundtrip_demo.py the
-- same way led_walk_demo.py resolved pulse_fifo's, not assumed.
-- WireOut 0x2E/0x2F expose ddr3_write_fifo/ddr3_read_fifo occupancy
-- (plus write-path-idle on 0x2E bit 5) for bring-up visibility, same
-- pattern as Phase 3's FIFO status endpoints.
--
-- IMPORTANT read-timing adaptation: the legacy design drove
-- pulser_ram's read-port clock (there called pulser_ram_clkb) as a
-- manually-toggled pulse from its own FSM -- effectively a
-- software-generated clock, strobed only when a new word was
-- needed. Our Vivado-generated pulser_ram has a real, continuously
-- running clkb (tied to clk_100, "Always Enabled", fixed 1-cycle
-- read latency, no enable pin), so that toggle scheme can't be
-- ported literally. The FSM below was redesigned around this
-- simpler always-on read port, but preserves the one thing that
-- must match exactly for existing pulse programs to keep meaning
-- the same real-world timing: time_count still advances once every
-- 4 clk_100 cycles (40 ns/tick @ 100 MHz), identical to the legacy
-- tick rate. This should be double-checked (scope on logic_out, or
-- simulation) before trusting it for real experiment timing.
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

		-- Phase 6a: MIG (src/ip/ddr3_256_16) owns these physical pins
		-- directly (System Clock = Differential) -- no more IBUFGDS/
		-- sys_clk in this file, see file header comment. Renamed from
		-- sys_clkp/sys_clkn to match ramtester's sys_clk_p/sys_clk_n
		-- convention, since constraints/xem7305.xdc's DDR3 pin block
		-- will be copied from there in the next step.
		sys_clk_p : in     STD_LOGIC;
		sys_clk_n : in     STD_LOGIC;

		led       : out    STD_LOGIC_VECTOR(3 downto 0);

		-- Phase 6a: MIG's physical DDR3 interface (src/ip/ddr3_256_16).
		-- Port names/widths match the generated ddr3_256_16.vhd wrapper
		-- exactly; pin/IOSTANDARD constraints not yet added to
		-- constraints/xem7305.xdc (next step, copied from
		-- ../XEM7305_references/Locally_compiled_ramtester's proven xdc).
		ddr3_dq       : inout  STD_LOGIC_VECTOR(15 downto 0);
		ddr3_dqs_p    : inout  STD_LOGIC_VECTOR(1 downto 0);
		ddr3_dqs_n    : inout  STD_LOGIC_VECTOR(1 downto 0);
		ddr3_addr     : out    STD_LOGIC_VECTOR(14 downto 0);
		ddr3_ba       : out    STD_LOGIC_VECTOR(2 downto 0);
		ddr3_ras_n    : out    STD_LOGIC;
		ddr3_cas_n    : out    STD_LOGIC;
		ddr3_we_n     : out    STD_LOGIC;
		ddr3_reset_n  : out    STD_LOGIC;
		ddr3_ck_p     : out    STD_LOGIC_VECTOR(0 downto 0);
		ddr3_ck_n     : out    STD_LOGIC_VECTOR(0 downto 0);
		ddr3_cke      : out    STD_LOGIC_VECTOR(0 downto 0);
		ddr3_dm       : out    STD_LOGIC_VECTOR(1 downto 0);
		ddr3_odt      : out    STD_LOGIC_VECTOR(0 downto 0);

		-- 6-bit LED header (see constraints/xem7305.xdc, pins copied from
		-- ../XEM7305_references/Locally_compiled_ramtester -- LVCMOS33, a
		-- different bank/voltage than the onboard led[3:0] above, so this
		-- is a separate add-on LED board/header, not more onboard LEDs).
		-- Carries logic_out(5 downto 0) for Phase 5a bring-up -- see below.
		led_ext   : out    STD_LOGIC_VECTOR(5 downto 0)
	);
end photon;

architecture arch of photon is
	-- Phase 6a: MIG DDR3 controller (src/ip/ddr3_256_16), instantiated
	-- as pure bring-up (app_* interface tied inert) -- see file header
	-- comment. Component port list matches the generated
	-- ddr3_256_16.vhd wrapper exactly (Xilinx MIG 7-series, Native
	-- interface, generated via create_project.tcl's
	-- CONFIG.XML_INPUT_FILE pointing at mig_b.prj -- see
	-- ../XEM7305_references/Locally_compiled_ramtester).
	component ddr3_256_16 port (
		ddr3_dq       : inout STD_LOGIC_VECTOR(15 downto 0);
		ddr3_dqs_p    : inout STD_LOGIC_VECTOR(1 downto 0);
		ddr3_dqs_n    : inout STD_LOGIC_VECTOR(1 downto 0);
		ddr3_addr     : out   STD_LOGIC_VECTOR(14 downto 0);
		ddr3_ba       : out   STD_LOGIC_VECTOR(2 downto 0);
		ddr3_ras_n    : out   STD_LOGIC;
		ddr3_cas_n    : out   STD_LOGIC;
		ddr3_we_n     : out   STD_LOGIC;
		ddr3_reset_n  : out   STD_LOGIC;
		ddr3_ck_p     : out   STD_LOGIC_VECTOR(0 downto 0);
		ddr3_ck_n     : out   STD_LOGIC_VECTOR(0 downto 0);
		ddr3_cke      : out   STD_LOGIC_VECTOR(0 downto 0);
		ddr3_dm       : out   STD_LOGIC_VECTOR(1 downto 0);
		ddr3_odt      : out   STD_LOGIC_VECTOR(0 downto 0);

		app_addr                  : in    STD_LOGIC_VECTOR(28 downto 0);
		app_cmd                   : in    STD_LOGIC_VECTOR(2 downto 0);
		app_en                    : in    STD_LOGIC;
		app_wdf_data              : in    STD_LOGIC_VECTOR(127 downto 0);
		app_wdf_end               : in    STD_LOGIC;
		app_wdf_mask              : in    STD_LOGIC_VECTOR(15 downto 0);
		app_wdf_wren              : in    STD_LOGIC;
		app_rd_data               : out   STD_LOGIC_VECTOR(127 downto 0);
		app_rd_data_end           : out   STD_LOGIC;
		app_rd_data_valid         : out   STD_LOGIC;
		app_rdy                   : out   STD_LOGIC;
		app_wdf_rdy               : out   STD_LOGIC;
		app_sr_req                : in    STD_LOGIC;
		app_ref_req               : in    STD_LOGIC;
		app_zq_req                : in    STD_LOGIC;
		app_sr_active             : out   STD_LOGIC;
		app_ref_ack               : out   STD_LOGIC;
		app_zq_ack                : out   STD_LOGIC;
		ui_clk                    : out   STD_LOGIC;
		ui_clk_sync_rst           : out   STD_LOGIC;
		init_calib_complete       : out   STD_LOGIC;
		sys_clk_p                 : in    STD_LOGIC;
		sys_clk_n                 : in    STD_LOGIC;
		device_temp               : out   STD_LOGIC_VECTOR(11 downto 0);
		sys_rst                   : in    STD_LOGIC
	);
	end component;

	signal ui_clk              : STD_LOGIC;
	signal ui_clk_sync_rst     : STD_LOGIC;
	signal init_calib_complete : STD_LOGIC;

	-- MIG requires an active-high sys_rst pulse >=5 ns after
	-- configuration (UG586); a single okClk cycle (okClk is the
	-- earliest clock guaranteed running, independent of MIG's own PLL
	-- which sys_rst gates) is ample margin -- same approach as
	-- ramtester's rst_cnt logic. Initial value '1' relies on the FF's
	-- configuration-time INIT state, same as ramtester's Verilog
	-- `initial rst_cnt = 0`.
	signal mig_sys_rst : STD_LOGIC := '1';

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

	-- Phase 6b: DDR3 write/read adapters (see file header comment).
	-- ddr3_write_fifo: bring-up drain process (clk_100) -> write-
	-- assembler (ui_clk), 64-bit both sides (same word width as
	-- pulse_fifo's read side/pulser_ram). ddr3_read_fifo: read-prefetch
	-- (ui_clk) -> BTPipeOut 0xA3 (okClk), 64-bit write / 32-bit read
	-- (asymmetric -- see its own component comment below for why).
	-- Both 32 deep (write-side units) as a first cut -- revisit once
	-- Phase 6d's BRAM budget across all FIFOs is known. Independent
	-- Clocks Block RAM FIFO, First-Word-Fall-Through, same settings as
	-- pulse_fifo/fifo_photon; generated manually in the Vivado IP
	-- catalog like the other Phase 3 FIFOs, not checked in.
	component ddr3_write_fifo port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(63 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(63 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(4 downto 0) -- 32-deep
	);
	end component;

	-- ddr3_read_fifo is natively asymmetric (64-bit write / 32-bit read)
	-- so poA3 below can wire directly to it with zero intermediary
	-- logic, matching every other BTPipeOut here -- an earlier version
	-- tried a symmetric 64-bit FIFO plus a hand-rolled registered
	-- toggle to split each word across two pipe reads, which broke
	-- okBTPipeOut's internal timing assumptions (it expects a direct
	-- FWFT connection) and produced a duplicated/shifted readback
	-- pattern on real hardware. rd_data_count is 6 bits (confirmed
	-- against the generated IP's Data Counts tab) -- wider than
	-- ddr3_write_fifo's 5, since one 64-bit write yields two 32-bit
	-- reads.
	-- Phase 6b (ramtester refactor): 128-bit write / 32-bit read,
	-- STANDARD FIFO (not FWFT), independent clocks -- matches
	-- Locally_compiled_ramtester's fifo_w128_256_r32_1024. Read-prefetch
	-- pushes the whole 128-bit MIG response in one write; the FIFO does
	-- the 128->32 conversion so BTPipeOut 0xA3 reads 32 bits directly
	-- (with an rd_data_count-gated ep_ready, see ddr3_read_pipe_ready).
	-- Standard (not FWFT) is deliberate: it has none of the asymmetric-
	-- FWFT lookahead quirks that made the earlier 64/32 FWFT FIFO need
	-- priming/flush/offset gymnastics. Regenerate the IP to match the
	-- ramtester settings: Fifo Implementation Independent Clocks Block
	-- RAM, Read Mode Standard FIFO, Write Width 128 / Write Depth 256,
	-- Read Width 32 (Read Depth 1024), Reset Pin on (Async + Reset
	-- Synchronization), Valid Flag on, Write Data Count on (8) and Read
	-- Data Count on (10).
	component ddr3_read_fifo port (
		rst    : in  STD_LOGIC;
		wr_clk : in  STD_LOGIC;
		rd_clk : in  STD_LOGIC;
		din    : in  STD_LOGIC_VECTOR(127 downto 0);
		wr_en  : in  STD_LOGIC;
		rd_en  : in  STD_LOGIC;
		dout   : out STD_LOGIC_VECTOR(31 downto 0);
		full   : out STD_LOGIC;
		empty  : out STD_LOGIC;
		rd_data_count : out STD_LOGIC_VECTOR(9 downto 0);
		wr_data_count : out STD_LOGIC_VECTOR(7 downto 0)
	);
	end component;

	signal ddr3_write_din          : STD_LOGIC_VECTOR(63 downto 0);
	signal ddr3_write_wr_en        : STD_LOGIC := '0';
	signal ddr3_write_rd_en        : STD_LOGIC;
	signal ddr3_write_dout         : STD_LOGIC_VECTOR(63 downto 0);
	signal ddr3_write_full         : STD_LOGIC;
	signal ddr3_write_empty        : STD_LOGIC;
	signal ddr3_write_rd_data_count : STD_LOGIC_VECTOR(4 downto 0);

	signal ddr3_read_din           : STD_LOGIC_VECTOR(127 downto 0);
	signal ddr3_read_wr_en         : STD_LOGIC := '0';
	signal ddr3_read_rd_en         : STD_LOGIC;
	signal ddr3_read_dout          : STD_LOGIC_VECTOR(31 downto 0);
	signal ddr3_read_full          : STD_LOGIC;
	signal ddr3_read_empty         : STD_LOGIC;
	signal ddr3_read_rd_data_count : STD_LOGIC_VECTOR(9 downto 0);
	signal ddr3_read_wr_data_count : STD_LOGIC_VECTOR(7 downto 0);
	-- Per-batch read-FIFO reset (level, host-controlled via ep00wire(6)).
	-- Clears ONLY the read FIFO and read-prefetch state (rd_pf_state/
	-- issued), NOT the addresses (rd_pf_addr/wr_asm_addr), so each
	-- soak-test batch starts from an empty read FIFO while the DDR3
	-- address walk continues across batches. The FIFO IP's rst is
	-- asynchronous, so driving it from this okClk-domain WireIn level is
	-- fine; the host holds it asserted with generous margin (ms) around
	-- each batch's read.
	signal ddr3_read_fifo_rst      : STD_LOGIC;

	-- MIG app_* command/write-data interface, now driven by the
	-- write-assembler/read-prefetch process below instead of tied
	-- inert (Phase 6a). app_wdf_end/app_wdf_mask are wired to constants
	-- directly in ddr3_inst's port map rather than routed through
	-- signals here, since this design only ever does single-beat
	-- (BL8/128-bit), full-width (no byte masking) bursts.
	signal mig_app_addr          : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	signal mig_app_cmd           : STD_LOGIC_VECTOR(2 downto 0)  := "000";
	signal mig_app_en            : STD_LOGIC := '0';
	signal mig_app_wdf_data      : STD_LOGIC_VECTOR(127 downto 0) := (others => '0');
	signal mig_app_wdf_wren      : STD_LOGIC := '0';
	signal mig_app_rd_data       : STD_LOGIC_VECTOR(127 downto 0);
	signal mig_app_rd_data_valid : STD_LOGIC;
	signal mig_app_rdy           : STD_LOGIC;
	signal mig_app_wdf_rdy       : STD_LOGIC;

	-- Phase 6c dual-path integration. mig_app_addr/cmd/en (above) are now the
	-- MUX outputs feeding MIG. The write-assembler/read-prefetch process drives
	-- wr_rd_app_* instead; the DDR3 line streamer drives str_app_*. A mode bit
	-- (ep00wire(5)) selects the DDR3 sequencer over the legacy pulser_ram FSM;
	-- the streamer takes MIG's command channel while a DDR3 sequence runs.
	signal wr_rd_app_addr : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	signal wr_rd_app_cmd  : STD_LOGIC_VECTOR(2 downto 0)  := "000";
	signal wr_rd_app_en   : STD_LOGIC := '0';
	signal str_app_addr   : STD_LOGIC_VECTOR(28 downto 0);
	signal str_app_cmd    : STD_LOGIC_VECTOR(2 downto 0);
	signal str_app_en     : STD_LOGIC;
	signal str_line_dout  : STD_LOGIC_VECTOR(63 downto 0);
	signal str_line_empty : STD_LOGIC;
	signal str_line_rd_en : STD_LOGIC;
	signal str_restart    : STD_LOGIC;                       -- clk_100, from sequencer
	signal str_restart_ui : STD_LOGIC;                       -- ui_clk, via pulse_cdc
	signal str_primed     : STD_LOGIC;                       -- ui_clk, from streamer
	signal str_primed_seq : STD_LOGIC;                       -- clk_100, via level_sync
	signal str_overflow   : STD_LOGIC;                       -- streamer sticky drop flag (ui_clk)
	signal str_line_count : STD_LOGIC_VECTOR(31 downto 0);   -- lines the sequencer popped (clk_100)
	signal ddr3_seq_mode  : STD_LOGIC;                       -- ep00wire(5): use DDR3 sequencer
	signal stream_active  : STD_LOGIC;                       -- ddr3_seq_mode AND running
	signal stream_active_ui : STD_LOGIC;                     -- ui_clk, via level_sync
	signal streamer_ui_rst  : STD_LOGIC;                     -- reset streamer between runs
	signal master_logic_ram  : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal master_logic_ddr3 : STD_LOGIC_VECTOR(31 downto 0);
	signal pulser_done_ram   : STD_LOGIC;
	signal pulser_done_ddr3  : STD_LOGIC;
	signal seq_count_ram     : STD_LOGIC_VECTOR(15 downto 0);
	signal seq_count_ddr3    : STD_LOGIC_VECTOR(15 downto 0);

	-- write-assembler state (ui_clk domain): pairs two ddr3_write_fifo
	-- words into one 128-bit MIG write burst (first popped -> low 64
	-- bits, second -> high 64 bits -- an explicit choice made in the
	-- process below, not an empirically-discovered FIFO behavior).
	-- wr_asm_addr is already in app_addr units (MIG-native 16-bit
	-- words), advancing by ADDRESS_INCREMENT=8 per burst --
	-- sequential-only, no arbitrary addressing needed yet (matches
	-- this design's access pattern). IMPORTANT: a burst only completes
	-- once a *second* word has been popped -- an odd total word count
	-- leaves this stuck in state 2 forever waiting for a word that
	-- never comes, so wr_asm_idle never reasserts either. The host
	-- must always write an even number of 64-bit words (pad with a
	-- dummy if needed, same as this project's other pipe writers
	-- already pad to the block size).
	signal wr_asm_state     : INTEGER range 0 to 3 := 0;
	signal wr_asm_low       : STD_LOGIC_VECTOR(63 downto 0);
	signal wr_asm_addr      : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	signal wr_asm_cmd_done  : STD_LOGIC := '0';
	signal wr_asm_data_done : STD_LOGIC := '0';
	signal wr_asm_idle      : STD_LOGIC := '1';

	-- read-prefetch state (ui_clk domain): single read outstanding at a
	-- time (correctness over max throughput -- plenty for this bring-up
	-- test's data rate). Ramtester-style single-push: state 0 issues a
	-- read, state 1 waits for app_rdy, state 2 pushes the WHOLE 128-bit
	-- response into the 128-write/32-read ddr3_read_fifo in one write.
	-- Only runs while ep00wire(4)='1' (read mode) -- see the combined
	-- write-assembler/read-prefetch process below for why reads and
	-- writes are time-multiplexed onto MIG's single shared command
	-- channel via this host-controlled bit instead of a runtime arbiter.
	signal rd_pf_state      : INTEGER range 0 to 2 := 0;
	signal rd_pf_addr       : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	-- Lost-command retry: MIG 7 occasionally counts a read command as
	-- accepted (app_rdy sampled high) but never returns app_rd_data_valid
	-- for it -- a known app_rdy edge-timing issue (falling edge right at
	-- the clock edge). To recover, the address advance and command count
	-- are committed on VALID (not on app_rdy), and state 2 times out after
	-- rd_pf_wait_ctr cycles -- far beyond any real read latency, so a
	-- merely-slow valid always arrives first -- and re-issues the same
	-- (un-advanced) address. RD_PF_TIMEOUT ~2047 ui_clk (~25 us at
	-- 81 MHz) vs. a normal read latency well under 1 us.
	signal rd_pf_wait_ctr   : INTEGER range 0 to 2047 := 0;

	-- DIAGNOSTIC (temporary, WireOut 0x30): counts rising edges of
	-- mig_app_rd_data_valid (not every cycle it's held high -- a first
	-- version of this counter did that and got confusingly large
	-- numbers, which turned out to be ambiguous between "many separate
	-- pulses" and "few pulses each held for many cycles") regardless
	-- of rd_pf_state, to test whether each MIG read command asserts it
	-- once (as assumed) or more than once.
	signal dbg_valid_count : STD_LOGIC_VECTOR(7 downto 0) := (others => '0');
	signal dbg_valid_prev  : STD_LOGIC := '0';

	-- DIAGNOSTIC (temporary, WireOut 0x31): counts how many read
	-- commands read-prefetch itself actually issues (accepted by MIG,
	-- i.e. rd_pf_addr incrementing), to cross-check against
	-- dbg_valid_count -- if they don't match, the mismatch is between
	-- issuing and MIG's response, not in how we process a response.
	signal dbg_cmd_count : STD_LOGIC_VECTOR(7 downto 0) := (others => '0');

	-- DIAGNOSTIC (temporary, WireOut 0x31 bits 15:8): how many times the
	-- lost-command retry fired (state-2 timeout re-issuing a read). Nonzero
	-- confirms the MIG app_rdy edge-timing issue was hit and recovered.
	signal dbg_retry_count : STD_LOGIC_VECTOR(7 downto 0) := (others => '0');

	-- DIAGNOSTIC (temporary, WireOut 0x32/0x33): the raw high-32 bits
	-- mig_app_rd_data actually returns for the first two commands'
	-- responses, latched directly in state 2 (see dbg_resp_count usage
	-- there) -- ground truth to compare against what the readback
	-- pipeline eventually presents, instead of inferring it indirectly.
	signal dbg_resp_count : INTEGER range 0 to 7 := 0;
	signal dbg_high0 : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal dbg_high1 : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');

	-- DIAGNOSTIC (temporary, WireOut 0x34): a soak-test run intermittently
	-- (not every run, same deterministic input data both times) showed
	-- one MIG read command's response duplicating the *previous*
	-- command's response -- ground truth to tell apart the two possible
	-- causes: rd_pf_addr failing to advance (same address legitimately
	-- re-read) vs. stale response data being pushed for a genuinely new
	-- address (a real data-path race). dbg_cmd_addr/dbg_prev_addr latch
	-- each command's own address (state 1) for comparison; dbg_prev_rd_data
	-- latches each command's raw 128-bit response (state 2, internal
	-- only, too wide to expose) for comparison against the *next*
	-- command's response. dbg_dup_count counts how many times two
	-- consecutive responses were bit-identical; dbg_dup_at_cmd latches
	-- dbg_cmd_count at the most recent occurrence; dbg_dup_addr_match
	-- records whether that pair's addresses also matched (an address
	-- bug) or differed (a data-path bug).
	signal dbg_cmd_addr       : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	signal dbg_prev_addr      : STD_LOGIC_VECTOR(28 downto 0) := (others => '0');
	signal dbg_prev_rd_data   : STD_LOGIC_VECTOR(127 downto 0) := (others => '0');
	signal dbg_dup_count      : STD_LOGIC_VECTOR(15 downto 0) := (others => '0');
	signal dbg_dup_at_cmd     : STD_LOGIC_VECTOR(15 downto 0) := (others => '0');
	signal dbg_dup_addr_match : STD_LOGIC := '0';

	-- DIAGNOSTIC (temporary): after the read command double-issue fix,
	-- an occasional stall appeared where read-prefetch issued a command
	-- (dbg_cmd_count) that got one fewer valid response (dbg_valid_count
	-- = cmd-1), leaving it stuck in the valid-wait state. dbg_valid_outside_s2
	-- is a sticky flag set if mig_app_rd_data_valid was ever seen while
	-- rd_pf_state /= 2 (the capture state) -- if set, read-prefetch
	-- MISSED a valid (bug (b)); if clear at a stall, MIG never returned
	-- a valid for a counted command (phantom accept, bug (a)). Exposed
	-- alongside rd_pf_state itself on WireOut 0x2F.
	signal dbg_valid_outside_s2 : STD_LOGIC := '0';

	-- rd_pf_idle (WireOut 0x2F bit 16): the host MUST check this before
	-- switching ep00wire(4) back to write mode. If read-prefetch is
	-- mid-transaction (address already advanced past MIG's app_rdy but
	-- app_rd_data_valid not yet seen), switching away drops that
	-- pending completion permanently -- MIG won't reassert
	-- app_rd_data_valid for an already-accepted command, so resuming
	-- read mode later would deadlock forever waiting for it.
	signal rd_pf_idle : STD_LOGIC := '1';

	-- Per-batch read command budget (WireIn 0x07, ep07wire): the host
	-- writes this batch's read-command count (words/2) before flipping
	-- ep00wire(4) to read mode; rd_pf_issued/target are latched off
	-- ep00wire(4)'s rising edge (below) and gate issuance so read-
	-- prefetch stops exactly at the requested count, keeping rd_pf_addr
	-- in lockstep with wr_asm_addr across batches instead of eagerly
	-- racing ahead into not-yet-written memory.
	signal ep07wire      : STD_LOGIC_VECTOR(31 downto 0);
	signal rd_pf_issued  : INTEGER range 0 to 65535 := 0;
	signal rd_pf_target  : INTEGER range 0 to 65535 := 0;
	signal ep00wire4_prev : STD_LOGIC := '0';

	-- WireOut endpoints (0x2E/0x2F) -- Phase 6b bring-up only, no
	-- legacy equivalent; see file header comment.
	signal ep2Ewire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep2Fwire : STD_LOGIC_VECTOR(31 downto 0);

	-- WireOut endpoints (0x30/0x31/0x32/0x33) -- DIAGNOSTIC (temporary),
	-- see dbg_valid_count/dbg_cmd_count/dbg_high0/dbg_high1 comments.
	signal ep30wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep31wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep32wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep33wire : STD_LOGIC_VECTOR(31 downto 0);
	-- WireOut endpoint (0x34) -- DIAGNOSTIC (temporary), see
	-- dbg_dup_count/dbg_dup_at_cmd/dbg_dup_addr_match comments.
	signal ep34wire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep35wire : STD_LOGIC_VECTOR(31 downto 0);   -- streamer/sequencer line-pop count

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

	-- Phase 5 (PMT) m2: normal-mode counting datapath (write side of
	-- normal_pmt_fifo). pmt_sim_pulse is the synthetic source; pmt_in_muxed
	-- selects synthetic vs real detector (real pin tied '0' until added).
	signal pmt_sim_pulse : STD_LOGIC;
	signal pmt_in_muxed  : STD_LOGIC;

	-- Phase 5a: pulse-sequence FSM. master_logic holds the RAM word
	-- currently in effect; logic_out is master_logic run through the
	-- per-channel force/invert override mux (ep02wire/ep03wire), same
	-- as the legacy design's LOGIC_OUT. master_logic itself has no
	-- pins; logic_out's low 6 bits reach led_ext (see entity port
	-- comment), the rest has no pins until Phase 4 -- see 0x2B/0x2C
	-- below for full-width host-side observation either way.
	signal master_logic : STD_LOGIC_VECTOR(31 downto 0) := (others => '0');
	signal logic_out    : STD_LOGIC_VECTOR(31 downto 0);

	-- Sequencer control, wired from the same WireIn/TriggerIn bits as
	-- the legacy design (ep00wire(1)/(2), ep40wire(0)).
	signal pulser_counter_reset : STD_LOGIC;
	signal pulser_infinite_loop : STD_LOGIC;
	signal pulser_start_bit     : STD_LOGIC;
	signal pulser_sequence_done : STD_LOGIC;
	signal seq_count_bit        : STD_LOGIC_VECTOR(15 downto 0);

	-- Phase 5b stub: the legacy FSM's state-0 wait gates on this pulse
	-- when line-triggering is enabled (ep00wire(3)='1'). The real
	-- line-trigger conditioning chain (logic_in(0) -> debounce -> user
	-- delay -> pulse) is Phase 5b, blocked on the same breakout-board
	-- pin as Phase 4. Tied to '0' for now: if a host enables
	-- line-triggering before Phase 5b exists, the sequencer will simply
	-- wait in state 0 forever rather than ever falsely triggering.
	signal line_triggering_pulse : STD_LOGIC := '0';

	-- WireOut endpoints (0x2B, 0x2C) — Phase 5a bring-up only, no
	-- legacy equivalent. logic_out has no pins to observe on yet
	-- (Phase 4), so it's exposed here instead; 0x2C bundles
	-- sequence-done and the running loop count into one word.
	signal ep2Bwire : STD_LOGIC_VECTOR(31 downto 0);
	signal ep2Cwire : STD_LOGIC_VECTOR(31 downto 0);

	-- WireOut endpoint (0x2D) — Phase 6a bring-up only, no legacy
	-- equivalent; see file header comment.
	signal ep2Dwire : STD_LOGIC_VECTOR(31 downto 0);

	-- Target interface bus (new-generation okHost)
	signal okClk      : STD_LOGIC;
	signal okHE       : STD_LOGIC_VECTOR(112 downto 0);
	signal okEH       : STD_LOGIC_VECTOR(64 downto 0);
	signal okEHx      : STD_LOGIC_VECTOR(65*27-1 downto 0); -- 27 endpoints need an okEH slot

	-- WireIn endpoints (0x00-0x06) — same addresses/roles as the legacy design
	signal ep00wire   : STD_LOGIC_VECTOR(31 downto 0); -- mode/config flags
	signal ep01wire   : STD_LOGIC_VECTOR(31 downto 0); -- normal PMT measure period
	signal ep02wire   : STD_LOGIC_VECTOR(31 downto 0); -- manual override select
	signal ep03wire   : STD_LOGIC_VECTOR(31 downto 0); -- manual override state/invert
	signal ep04wire   : STD_LOGIC_VECTOR(31 downto 0); -- DDS channel select
	signal ep05wire   : STD_LOGIC_VECTOR(31 downto 0); -- infinite-loop repeat count
	signal ep06wire   : STD_LOGIC_VECTOR(31 downto 0); -- line-trigger delay (us)

	-- Phase 5 (PMT) m2: normal-mode photon counting control.
	signal ep08wire   : STD_LOGIC_VECTOR(31 downto 0); -- PMT ctrl: b0 count_en, b1 sim_en
	signal ep09wire   : STD_LOGIC_VECTOR(31 downto 0); -- PMT synthetic-source period (clk_100 cycles)
	signal ep0Awire   : STD_LOGIC_VECTOR(31 downto 0); -- PMT collection gate length (clk_100 cycles)

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

	-- ddr3_read_fifo is a Standard FIFO (not FWFT), so BTPipeOut 0xA3
	-- gets a proper rd_data_count-gated ep_ready in the okClk domain,
	-- matching Locally_compiled_ramtester's pipe_out_ready. Asserted
	-- when at least one 16-byte block (4 x 32-bit read words) is
	-- available. rd_data_count is the FIFO's read-side (okClk) count,
	-- so reading it in okClk here is same-domain and safe.
	signal ddr3_read_pipe_ready : STD_LOGIC := '0';

	-- ui_clk heartbeat, proves MIG's PLL/ui_clk path independently of
	-- the USB-driven LEDs below (Phase 6a: was sys_clk/IBUFGDS directly
	-- -- see file header comment)
	signal heartbeat_div : STD_LOGIC_VECTOR(23 downto 0) := (others => '0');
begin

	------------------------------------------------------------------
	-- LEDs: bits 0-2 mirror WireIn 0x00, so writing that wire from the
	-- host is visible immediately. Bit 3 blinks off ui_clk to confirm
	-- MIG's PLL is running, independently of USB traffic (Phase 6a:
	-- was sys_clk/IBUFGDS directly -- see file header comment).
	------------------------------------------------------------------
	led(0) <= '0' when ep00wire(0) = '1' else 'Z';
	led(1) <= '0' when ep00wire(1) = '1' else 'Z';
	led(2) <= '0' when ep00wire(2) = '1' else 'Z';
	led(3) <= '0' when heartbeat_div(23) = '1' else 'Z';

	process (ui_clk)
	begin
		if rising_edge(ui_clk) then
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

	-- Phase 6b: per-batch read-FIFO reset, see ddr3_read_fifo_rst
	-- declaration comment.
	ddr3_read_fifo_rst <= ep00wire(6);

	-- Note: master_logic(17) is the legacy "TimeResolvedCount" bit --
	-- fifo_photon_wr_en would be wired to it directly in the legacy
	-- design, but fifo_photon_din (photon_time_tag) doesn't exist until
	-- Phase 5c's PMT-oversampling logic is built. Left tied to '0' for
	-- now (unchanged from Phase 3) rather than wired to master_logic(17)
	-- with nothing valid to write, which would silently stuff zeros into
	-- fifo_photon whenever a real pulse program sets that bit.

	------------------------------------------------------------------
	-- Phase 5 (PMT) m2: normal-mode photon-counting datapath.
	-- Drives the previously-unconnected normal_pmt_fifo write side
	-- (host reads counts over BTPipeOut 0xA1, fill level over WireOut
	-- 0x29, resets the FIFO with ep40wire(2)). The PMT input is muxed
	-- between an on-FPGA synthetic source (pmt_sim) and the real detector
	-- pin -- tied '0' until that pin is added -- the same dual-path trick
	-- as the DDR3 sequencer's ep00wire(5), so the detector wires in later
	-- without disturbing the datapath. Control:
	--   ep08wire(0) = counter enable (run periodic collection)
	--   ep08wire(1) = 1: synthetic source; 0: real pin
	--   ep09wire    = synthetic-source period (clk_100 cycles/pulse)
	--   ep0Awire    = collection gate length (clk_100 cycles/window)
	-- clk_100 domain (= normal_pmt_fifo wr_clk); async reset shared with
	-- the sequencer (pulser_counter_reset).
	------------------------------------------------------------------
	pmt_in_muxed <= pmt_sim_pulse when ep08wire(1) = '1' else '0';  -- else: real pin later

	pmt_source : entity work.pmt_sim
		generic map (PERIOD_W => 32)
		port map (clk => clk_100, reset => pulser_counter_reset,
		          enable => ep08wire(1), period => ep09wire,
		          pulse => pmt_sim_pulse);

	pmt_normal_counter : entity work.pmt_counter
		generic map (CNT_W => 32, GATE_W => 32)
		port map (clk => clk_100, reset => pulser_counter_reset,
		          enable => ep08wire(0), pmt_in => pmt_in_muxed,
		          gate_len => ep0Awire, fifo_full => normal_pmt_fifo_full,
		          fifo_wr_en => normal_pmt_fifo_wr_en,
		          fifo_din => normal_pmt_fifo_din, sample => open);

	------------------------------------------------------------------
	-- Phase 5a: sequencer control, same WireIn/TriggerIn bits as the
	-- legacy design. pulser_counter_reset is used as an async reset
	-- below, same as legacy -- same ep40wire/ui_clk-domain CDC caveat
	-- already flagged for ep40wire(1) in Phase 3 also applies here.
	------------------------------------------------------------------
	pulser_counter_reset <= ep40wire(0);
	pulser_infinite_loop <= ep00wire(1);
	pulser_start_bit     <= ep00wire(2);

	------------------------------------------------------------------
	-- Phase 5a: logic_out override mux, ported directly from the
	-- legacy design's LOGIC_OUT assignments. Channels 0-11 support
	-- per-channel manual override via ep02wire/ep03wire (00=follow
	-- master_logic, 01=invert, 10=force 0, 11=force 1); channels 12/13
	-- echo the DDS step/reset bits (master_logic(18)/(19)) same as the
	-- legacy design's "729 DDS BNC" outputs; 14/15 are unused (tied 0,
	-- matching legacy); 16-31 are a straight passthrough, no override.
	------------------------------------------------------------------
	logic_out(0) <= master_logic(0)     WHEN (ep02wire(0)='0' AND ep03wire(0)='0') ELSE
	                NOT master_logic(0) WHEN (ep02wire(0)='0' AND ep03wire(0)='1') ELSE
	                '0'                 WHEN (ep02wire(0)='1' AND ep03wire(0)='0') ELSE
	                '1';
	logic_out(1) <= master_logic(1)     WHEN (ep02wire(1)='0' AND ep03wire(1)='0') ELSE
	                NOT master_logic(1) WHEN (ep02wire(1)='0' AND ep03wire(1)='1') ELSE
	                '0'                 WHEN (ep02wire(1)='1' AND ep03wire(1)='0') ELSE
	                '1';
	logic_out(2) <= master_logic(2)     WHEN (ep02wire(2)='0' AND ep03wire(2)='0') ELSE
	                NOT master_logic(2) WHEN (ep02wire(2)='0' AND ep03wire(2)='1') ELSE
	                '0'                 WHEN (ep02wire(2)='1' AND ep03wire(2)='0') ELSE
	                '1';
	logic_out(3) <= master_logic(3)     WHEN (ep02wire(3)='0' AND ep03wire(3)='0') ELSE
	                NOT master_logic(3) WHEN (ep02wire(3)='0' AND ep03wire(3)='1') ELSE
	                '0'                 WHEN (ep02wire(3)='1' AND ep03wire(3)='0') ELSE
	                '1';
	logic_out(4) <= master_logic(4)     WHEN (ep02wire(4)='0' AND ep03wire(4)='0') ELSE
	                NOT master_logic(4) WHEN (ep02wire(4)='0' AND ep03wire(4)='1') ELSE
	                '0'                 WHEN (ep02wire(4)='1' AND ep03wire(4)='0') ELSE
	                '1';
	logic_out(5) <= master_logic(5)     WHEN (ep02wire(5)='0' AND ep03wire(5)='0') ELSE
	                NOT master_logic(5) WHEN (ep02wire(5)='0' AND ep03wire(5)='1') ELSE
	                '0'                 WHEN (ep02wire(5)='1' AND ep03wire(5)='0') ELSE
	                '1';
	logic_out(6) <= master_logic(6)     WHEN (ep02wire(6)='0' AND ep03wire(6)='0') ELSE
	                NOT master_logic(6) WHEN (ep02wire(6)='0' AND ep03wire(6)='1') ELSE
	                '0'                 WHEN (ep02wire(6)='1' AND ep03wire(6)='0') ELSE
	                '1';
	logic_out(7) <= master_logic(7)     WHEN (ep02wire(7)='0' AND ep03wire(7)='0') ELSE
	                NOT master_logic(7) WHEN (ep02wire(7)='0' AND ep03wire(7)='1') ELSE
	                '0'                 WHEN (ep02wire(7)='1' AND ep03wire(7)='0') ELSE
	                '1';
	logic_out(8) <= master_logic(8)     WHEN (ep02wire(8)='0' AND ep03wire(8)='0') ELSE
	                NOT master_logic(8) WHEN (ep02wire(8)='0' AND ep03wire(8)='1') ELSE
	                '0'                 WHEN (ep02wire(8)='1' AND ep03wire(8)='0') ELSE
	                '1';
	logic_out(9) <= master_logic(9)     WHEN (ep02wire(9)='0' AND ep03wire(9)='0') ELSE
	                NOT master_logic(9) WHEN (ep02wire(9)='0' AND ep03wire(9)='1') ELSE
	                '0'                 WHEN (ep02wire(9)='1' AND ep03wire(9)='0') ELSE
	                '1';
	logic_out(10) <= master_logic(10)     WHEN (ep02wire(10)='0' AND ep03wire(10)='0') ELSE
	                  NOT master_logic(10) WHEN (ep02wire(10)='0' AND ep03wire(10)='1') ELSE
	                  '0'                  WHEN (ep02wire(10)='1' AND ep03wire(10)='0') ELSE
	                  '1';
	logic_out(11) <= master_logic(11)     WHEN (ep02wire(11)='0' AND ep03wire(11)='0') ELSE
	                  NOT master_logic(11) WHEN (ep02wire(11)='0' AND ep03wire(11)='1') ELSE
	                  '0'                  WHEN (ep02wire(11)='1' AND ep03wire(11)='0') ELSE
	                  '1';
	logic_out(12) <= master_logic(18); -- DDS step-to-next-value
	logic_out(13) <= master_logic(19); -- DDS reset
	logic_out(14) <= '0';
	logic_out(15) <= '0';
	logic_out(31 downto 16) <= master_logic(31 downto 16);

	------------------------------------------------------------------
	-- Phase 5a bring-up (0x2B/0x2C): logic_out has no pins yet
	-- (Phase 4), so expose it directly on a WireOut for host-side
	-- verification, plus sequence-done (bit 16) and the running loop
	-- count (bits 15:0, same as legacy's seq_count_bit).
	------------------------------------------------------------------
	ep2Bwire <= logic_out;
	-- bit 17 = streamer dropped-beat flag (sticky, ui_clk): stays 0 if no beat
	-- was ever pushed into a full line FIFO -- the host reads it after a long
	-- run to confirm no silent drops (see ddr3_line_streamer dbg_overflow).
	ep2Cwire <= (31 downto 18 => '0') & str_overflow & pulser_sequence_done & seq_count_bit;

	------------------------------------------------------------------
	-- Phase 6a bring-up (0x2D): MIG calibration status, since nothing
	-- else surfaces it yet (Phase 6b's read/write adapters will gate
	-- on this internally once they exist).
	------------------------------------------------------------------
	ep2Dwire <= (0 => init_calib_complete, others => '0');

	------------------------------------------------------------------
	-- Phase 6b bring-up (0x2E/0x2F): ddr3_write_fifo/ddr3_read_fifo
	-- occupancy, so a host script can watch data move through the new
	-- DDR3 write/read adapters. 0x2E bit 5 = write path fully idle
	-- (write_fifo empty AND write-assembler not mid-transaction) --
	-- check this before switching ep00wire(4) to read mode, see file
	-- header comment.
	------------------------------------------------------------------
	ep2Ewire <= (31 downto 6 => '0') & wr_asm_idle & ddr3_write_rd_data_count;
	-- WireOut 0x2F layout: bits 9:0 = ddr3_read_rd_data_count (read-side,
	-- okClk-synchronized); bits 12:10 = rd_pf_state (0-2); bit 13 =
	-- ddr3_read_empty; bit 14 = dbg_valid_outside_s2 (diagnostic);
	-- bit 16 = rd_pf_idle (host MUST check this before switching
	-- ep00wire(4) back to write mode, see rd_pf_idle comment); bits
	-- 25:18 = rd_pf_issued (how many read commands this batch has
	-- issued -- the host waits for issued>=target AND idle, both pure
	-- ui_clk-domain state, to know the batch is done). ddr3_read_empty
	-- is a single-bit flag, safe to gate ReadFromBlockPipeOut on (that
	-- call has no software timeout, so reading before data has crossed
	-- into okClk would hang).
	ep2Fwire <= (31 downto 26 => '0') & CONV_STD_LOGIC_VECTOR(rd_pf_issued, 8) &
	            '0' & rd_pf_idle & '0' & dbg_valid_outside_s2 & ddr3_read_empty &
	            CONV_STD_LOGIC_VECTOR(rd_pf_state, 3) & ddr3_read_rd_data_count;

	------------------------------------------------------------------
	-- DIAGNOSTIC (temporary, WireOut 0x30): see dbg_valid_count
	-- declaration comment.
	------------------------------------------------------------------
	ep30wire <= (31 downto 8 => '0') & dbg_valid_count;
	ep31wire <= (31 downto 16 => '0') & dbg_retry_count & dbg_cmd_count;
	ep32wire <= dbg_high0;
	ep33wire <= dbg_high1;
	-- bits 31:16: dbg_dup_at_cmd. bits 15:1: dbg_dup_count. bit 0:
	-- dbg_dup_addr_match. See dbg_dup_count declaration comment.
	ep34wire <= dbg_dup_at_cmd & dbg_dup_count(14 downto 0) & dbg_dup_addr_match;
	-- WireOut 0x35: lines the DDR3 sequencer popped this run (integrity check --
	-- host compares to program length + 1; catches a dropped/duplicated line
	-- from any cause, not just FIFO overflow). See pulse_sequencer line_count.
	ep35wire <= str_line_count;

	process (ui_clk)
	begin
		if rising_edge(ui_clk) then
			dbg_valid_prev <= mig_app_rd_data_valid;
			if ep40wire(5) = '1' then
				dbg_valid_count <= (others => '0');
			elsif mig_app_rd_data_valid = '1' and dbg_valid_prev = '0' then
				dbg_valid_count <= dbg_valid_count + 1;
			end if;
		end if;
	end process;

	-- Assumed active-high (a bit lit = LED on), unlike the onboard led[3:0]
	-- above which are active-low. led_ext is presumed a separate add-on LED
	-- board wired the ordinary way (LED positive lead to the FPGA pin
	-- through a series resistor) rather than Opal Kelly's own onboard
	-- open-drain-style LEDs -- if channels appear inverted on hardware,
	-- change this to "not logic_out(5 downto 0)".
	led_ext <= logic_out(5 downto 0);

	-- Phase 3 bring-up only: drains pulse_fifo into pulser_ram at an
	-- auto-incrementing address. pulse_fifo is First-Word-Fall-Through,
	-- so dout is already valid whenever empty='0' -- no extra wait state
	-- needed before latching it. ep40wire(1) resets the write address,
	-- matching the legacy design's pulser_ram_reset bit.
	--
	-- Phase 6b: the same popped word is also fed into ddr3_write_fifo
	-- in lockstep, so the existing host write path (BTPipeIn 0x80)
	-- exercises the new DDR3 write path too, without a separate pipe.
	-- Gated on ddr3_write_full so a lagging DDR3 write path throttles
	-- this drain process rather than silently dropping data -- harmless
	-- for pulser_ram/Phase 5a's tests, which never queue enough at once
	-- to fill a 32-deep FIFO.
	process (clk_100)
	begin
		if rising_edge(clk_100) then
			fifo_pulser_rd_en <= '0';
			pulser_ram_wea    <= "0";
			ddr3_write_wr_en  <= '0';
			if ep40wire(1) = '1' then
				ram_write_addr  <= (others => '0');
				ram_write_state <= 0;
			else
				case ram_write_state is
					when 0 =>
						if fifo_pulser_empty = '0' and ddr3_write_full = '0' then
							pulser_ram_dina   <= fifo_pulser_dout;
							pulser_ram_addra  <= ram_write_addr;
							fifo_pulser_rd_en <= '1';
							ddr3_write_din    <= fifo_pulser_dout;
							ddr3_write_wr_en  <= '1';
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

	------------------------------------------------------------------
	-- Phase 5a: main pulse-sequence FSM. See file header comment for
	-- the RAM-read-timing adaptation this makes relative to the
	-- legacy design. ram_process_count states 0-4 mirror the legacy
	-- design's initial two-word pipeline fill 1:1 (state numbering and
	-- intent unchanged, only the RAM-read mechanics inside states 1/3
	-- differ -- see comments below); state 5 is the main run loop,
	-- restructured around an unconditional 4-cycle count1 heartbeat
	-- (preserving the legacy 40 ns/tick rate) with the RAM
	-- read-ahead/word-transition work happening only at the count1=3
	-- tick boundary, since our RAM's data is already valid (no
	-- separate strobe/latency to hide) by the time we get there;
	-- state 6 is the same "limbo" done-state as legacy.
	------------------------------------------------------------------
	process (clk_100, pulser_counter_reset)
		variable seq_count         : INTEGER range 0 to 65535 := 0;
		variable count1            : INTEGER range 0 to 3 := 0;
		variable time_count        : INTEGER := 0;
		variable time_stamp        : INTEGER := 0;
		variable ram_read_address  : INTEGER range 0 to 1023 := 0;
		variable ram_process_count : INTEGER range 0 to 6 := 0;
		variable ram_data_out_1    : STD_LOGIC_VECTOR(63 downto 0);
		variable ram_data_out_2    : STD_LOGIC_VECTOR(63 downto 0);
	begin
		if pulser_counter_reset = '1' then
			ram_process_count := 0;
			ram_read_address  := 0;
			count1             := 0;
			time_count         := 0;
			time_stamp         := 0;
			master_logic_ram     <= (others => '0');
			pulser_done_ram      <= '0';
			seq_count          := 0;
		elsif rising_edge(clk_100) then
			if pulser_start_bit = '1' then
				case ram_process_count is

					-- wait for line trigger (Phase 5b stub, see
					-- line_triggering_pulse declaration) or fall
					-- through immediately if disabled
					when 0 =>
						ram_read_address := 0;
						if (ep00wire(3) = '1' and line_triggering_pulse = '1') or ep00wire(3) = '0' then
							ram_process_count := 1;
						end if;

					-- word 0: address 0 is now on pulser_ram_addrb
					-- (driven below from ram_read_address); wait one
					-- clk_100 cycle for our RAM's read latency
					when 1 =>
						ram_process_count := 2;

					when 2 =>
						master_logic_ram  <= pulser_ram_doutb(31 downto 0);
						ram_data_out_1    := pulser_ram_doutb;
						ram_read_address  := 1; -- prefetch word 1
						ram_process_count := 3;

					-- word 1: same one-cycle wait as above
					when 3 =>
						ram_process_count := 4;

					when 4 =>
						ram_data_out_2    := pulser_ram_doutb;
						time_stamp        := CONV_INTEGER(UNSIGNED(ram_data_out_2(62 downto 32)));
						ram_read_address  := 2; -- prefetch word 2, needed for the first run-loop transition
						count1             := 0;
						ram_process_count := 5;

					-- main run loop: count1 advances every clk_100
					-- cycle unconditionally (4 cycles = 40 ns/tick,
					-- matching the legacy design's tick rate exactly
					-- so existing pulse programs' timestamps mean the
					-- same real-world duration); the word transition
					-- only happens at the count1=3 tick boundary, and
					-- only when time_count is about to reach time_stamp
					when 5 =>
						if count1 = 3 then
							count1     := 0;
							time_count := time_count + 1;
							if time_count = time_stamp then
								-- ram_read_address hasn't changed since
								-- the last transition, so pulser_ram_doutb
								-- has been valid for several cycles already
								ram_data_out_1   := ram_data_out_2;
								ram_data_out_2   := pulser_ram_doutb;
								ram_read_address := ram_read_address + 1;
								time_stamp       := CONV_INTEGER(UNSIGNED(ram_data_out_2(62 downto 32)));
								if time_stamp = 0 then
									-- end-of-sequence sentinel word reached
									if pulser_infinite_loop = '1' then
										ram_process_count := 0;
										ram_read_address  := 0;
										count1             := 0;
										time_count         := 0;
										time_stamp         := 0;
										master_logic_ram  <= ram_data_out_1(31 downto 0);
										seq_count          := seq_count + 1;
										if CONV_INTEGER(UNSIGNED(ep05wire(15 downto 0))) /= 0 and
										   seq_count = CONV_INTEGER(UNSIGNED(ep05wire(15 downto 0))) then
											master_logic_ram  <= (others => '0');
											ram_process_count := 6;
										end if;
									else
										-- one-shot mode: done, go to limbo
										master_logic_ram  <= (others => '0');
										ram_process_count := 6;
									end if;
								else
									master_logic_ram <= ram_data_out_1(31 downto 0);
								end if;
							end if;
						else
							count1 := count1 + 1;
						end if;

					-- limbo: sequence done, stays here until pulser_counter_reset
					when 6 =>
						pulser_done_ram <= '1';

					when others => null;

				end case;
			end if;

			pulser_ram_addrb <= CONV_STD_LOGIC_VECTOR(ram_read_address, 10);
			seq_count_ram    <= CONV_STD_LOGIC_VECTOR(seq_count, 16);
		end if;
	end process;

	------------------------------------------------------------------
	-- Phase 6c: DDR3 line streamer + FIFO-fed sequencer (dual-path).
	-- ep00wire(5) selects the DDR3 sequencer over the legacy pulser_ram
	-- FSM; the streamer takes MIG's command channel while a DDR3 sequence
	-- runs. All legacy paths (write-assembler, read-prefetch, pulser_ram
	-- FSM) are untouched. See sim/ for the sim-verified modules and
	-- memory/ddr3-streamer-phase6c for the integration lessons.
	------------------------------------------------------------------
	ddr3_seq_mode <= ep00wire(5);
	stream_active <= ddr3_seq_mode and pulser_start_bit;
	-- reset (rewind + flush) the streamer whenever a DDR3 sequence is not
	-- actively running, so each run starts from line 0; loop-back rewinds go
	-- through the sequencer's restart pulse instead.
	streamer_ui_rst <= ui_clk_sync_rst or (not stream_active_ui);

	-- sequencer-output muxes (ddr3_seq_mode is a slow host-controlled level)
	master_logic         <= master_logic_ddr3 when ddr3_seq_mode = '1' else master_logic_ram;
	pulser_sequence_done <= pulser_done_ddr3   when ddr3_seq_mode = '1' else pulser_done_ram;
	seq_count_bit        <= seq_count_ddr3     when ddr3_seq_mode = '1' else seq_count_ram;

	-- MIG command-channel mux: the streamer while a DDR3 sequence runs,
	-- otherwise the write-assembler / read-prefetch.
	mig_app_addr <= str_app_addr when stream_active_ui = '1' else wr_rd_app_addr;
	mig_app_cmd  <= str_app_cmd  when stream_active_ui = '1' else wr_rd_app_cmd;
	mig_app_en   <= str_app_en   when stream_active_ui = '1' else wr_rd_app_en;

	-- CDC helpers (see src/pulse_cdc.vhd)
	sync_active : entity work.level_sync
		port map (dst_clk => ui_clk, d => stream_active, q => stream_active_ui);
	sync_primed : entity work.level_sync
		port map (dst_clk => clk_100, d => str_primed, q => str_primed_seq);
	restart_sync : entity work.pulse_cdc
		port map (src_clk => clk_100, src_pulse => str_restart,
		          dst_clk => ui_clk, dst_pulse => str_restart_ui);

	-- DDR3 line streamer (ui_clk): reads the program from DDR3 into the line
	-- FIFO for the sequencer to pop.
	ddr3_streamer : entity work.ddr3_line_streamer
		generic map (ADDR_WIDTH => 29, BASE_ADDR => 0, ADDR_INC => 8,
		             SCRATCH_XOR_BIT => 25, PRIME_BEATS => 8,
		             HEARTBEAT_CYCLES => 81, RETRY_TIMEOUT => 2047, DRAIN_CYCLES => 64)
		port map (ui_clk => ui_clk, ui_rst => streamer_ui_rst, seq_clk => clk_100,
		          run => stream_active_ui, restart => str_restart_ui, primed => str_primed,
		          app_addr => str_app_addr, app_cmd => str_app_cmd, app_en => str_app_en,
		          app_rdy => mig_app_rdy, app_rd_data => mig_app_rd_data,
		          app_rd_data_valid => mig_app_rd_data_valid,
		          line_rd_en => str_line_rd_en, line_dout => str_line_dout,
		          line_empty => str_line_empty,
		          dbg_retry_count => open, dbg_hb_count => open,
		          dbg_overflow => str_overflow);

	-- FIFO-fed pulse sequencer (clk_100): the DDR3 alternative to the legacy
	-- pulser_ram FSM. Drives the _ddr3 mux inputs.
	ddr3_sequencer : entity work.pulse_sequencer
		port map (clk => clk_100, reset => pulser_counter_reset,
		          start => pulser_start_bit, infinite => pulser_infinite_loop,
		          prog_ready => str_primed_seq,
		          line_trig_en => ep00wire(3), line_trig_pulse => line_triggering_pulse,
		          loop_limit => ep05wire(15 downto 0),
		          line_dout => str_line_dout, line_empty => str_line_empty,
		          line_rd_en => str_line_rd_en, restart => str_restart,
		          master_logic => master_logic_ddr3, seq_count_out => seq_count_ddr3,
		          seq_done => pulser_done_ddr3, line_count => str_line_count);

	------------------------------------------------------------------
	-- Phase 6b: write-assembler / read-prefetch, combined into one
	-- process since both drive MIG's shared app_addr/app_cmd/app_en
	-- command channel and only one signal driver is allowed. Reads and
	-- writes are time-multiplexed via ep00wire(4) (0=write mode,
	-- 1=read mode) rather than a runtime arbiter -- see file header
	-- comment for why (this is a standalone bring-up test with
	-- host-sequenced write-then-read phases, not concurrent access).
	--
	-- Write mode: pops a pair of words from ddr3_write_fifo (state 0
	-- captures the first and asserts rd_en; state 1 is a mandatory
	-- one-cycle wait for ddr3_write_rd_en's own register delay plus
	-- FWFT's pop-to-advance delay before ddr3_write_dout actually shows
	-- the second word; state 2 captures it and issues the MIG command),
	-- then holds app_en/app_wdf_wren asserted (state 3) until MIG
	-- accepts both the command and the write data (which may happen on
	-- different cycles), advancing wr_asm_addr by 8 only once both are
	-- confirmed.
	--
	-- Read mode: issues one read command (state 0, 1), waits for
	-- app_rd_data_valid (state 2, which pushes the low half immediately
	-- and latches the high half), then pushes the high half (state 3)
	-- into ddr3_read_fifo -- single request outstanding at a time.
	-- (Sampling both halves on the same cycle as valid, and pushing
	-- them a cycle apart, is confirmed correct -- both a one-cycle-
	-- later sampling attempt and a settling-cycle-before-push attempt
	-- were tested and ruled out; see dbg_high0/dbg_high1 for the
	-- current, still-open diagnostic.)
	------------------------------------------------------------------
	process (ui_clk)
	begin
		if rising_edge(ui_clk) then
			ddr3_write_rd_en <= '0';
			ddr3_read_wr_en  <= '0';
			wr_rd_app_en     <= '0';
			mig_app_wdf_wren <= '0';
			wr_asm_idle      <= '0';
			rd_pf_idle       <= '0';

			-- latch this batch's read-command budget on read mode's
			-- rising edge -- see rd_pf_issued/rd_pf_target declaration
			-- comment. Runs every cycle regardless of mode/reset below,
			-- same as any other edge detector.
			ep00wire4_prev <= ep00wire(4);
			if ep00wire(4) = '1' and ep00wire4_prev = '0' then
				rd_pf_issued  <= 0;
				rd_pf_target  <= CONV_INTEGER(UNSIGNED(ep07wire(15 downto 0)));
			end if;

			-- DIAGNOSTIC: sticky flag if a valid response ever arrives
			-- while read-prefetch is NOT in its capture state (2). Runs
			-- every cycle. See dbg_valid_outside_s2 declaration comment.
			if mig_app_rd_data_valid = '1' and rd_pf_state /= 2 then
				dbg_valid_outside_s2 <= '1';
			end if;

			if ep40wire(5) = '1' then
				wr_asm_state  <= 0;
				wr_asm_addr   <= (others => '0');
				rd_pf_state   <= 0;
				rd_pf_addr    <= (others => '0');
				dbg_cmd_count  <= (others => '0');
				dbg_resp_count <= 0;
				rd_pf_issued   <= 0;
				rd_pf_target   <= 0;
				rd_pf_wait_ctr <= 0;
				dbg_retry_count    <= (others => '0');
				dbg_dup_count      <= (others => '0');
				dbg_dup_at_cmd     <= (others => '0');
				dbg_dup_addr_match <= '0';
				dbg_prev_rd_data   <= (others => '0');
				dbg_prev_addr      <= (others => '0');
				dbg_valid_outside_s2 <= '0';
			elsif ddr3_read_fifo_rst = '1' then
				-- per-batch read-FIFO reset (see ddr3_read_fifo_rst
				-- declaration comment): clean read-side state so each
				-- batch starts from an empty FIFO, but preserve
				-- rd_pf_addr/wr_asm_addr so the DDR3 address walk
				-- continues across batches.
				rd_pf_state    <= 0;
				rd_pf_issued   <= 0;
			elsif ep00wire(4) = '0' then
				-- write mode
				case wr_asm_state is
					when 0 =>
						wr_asm_idle <= ddr3_write_empty;
						if ddr3_write_empty = '0' then
							wr_asm_low       <= ddr3_write_dout;
							ddr3_write_rd_en <= '1';
							wr_asm_state     <= 1;
						end if;
					when 1 =>
						-- wait one cycle: ddr3_write_rd_en is itself a
						-- registered signal, so the FIFO doesn't see the
						-- pop asserted in state 0 as an input until this
						-- cycle, and FWFT only advances dout to the next
						-- word starting the cycle after that -- reading
						-- dout here (one cycle too early) would just see
						-- the same first word again (the exact bug this
						-- state exists to avoid; see the proven drain
						-- process above, which never re-reads dout the
						-- cycle immediately after asserting rd_en either).
						wr_asm_state <= 2;
					when 2 =>
						if ddr3_write_empty = '0' then
							mig_app_wdf_data <= ddr3_write_dout & wr_asm_low;
							wr_rd_app_addr   <= wr_asm_addr;
							wr_rd_app_cmd    <= "000";
							wr_rd_app_en     <= '1';
							mig_app_wdf_wren <= '1';
							ddr3_write_rd_en <= '1';
							wr_asm_cmd_done  <= '0';
							wr_asm_data_done <= '0';
							wr_asm_state     <= 3;
						end if;
					when others => -- 3: hold until MIG accepts cmd + data
						if mig_app_rdy = '1' then
							wr_asm_cmd_done <= '1';
						else
							wr_rd_app_en   <= '1';
							wr_rd_app_addr <= wr_asm_addr;
							wr_rd_app_cmd  <= "000";
						end if;
						if mig_app_wdf_rdy = '1' then
							wr_asm_data_done <= '1';
						else
							mig_app_wdf_wren <= '1';
						end if;
						if (wr_asm_cmd_done = '1' or mig_app_rdy = '1') and
						   (wr_asm_data_done = '1' or mig_app_wdf_rdy = '1') then
							wr_asm_addr  <= wr_asm_addr + 8;
							wr_asm_state <= 0;
						end if;
				end case;
			else
				-- read mode -- only entered once the host has confirmed
				-- the write path is idle (WireOut 0x2E bit 5). Ramtester-
				-- style single-push design (see Locally_compiled_ramtester
				-- ddr3_test.v s_read_0/1/2): issue one read (state 0), wait
				-- for app_rdy while deasserting app_en once accepted
				-- (state 1), then on app_rd_data_valid push the WHOLE
				-- 128-bit response into the 128-write/32-read ddr3_read_fifo
				-- in a SINGLE write (state 2). The FIFO does the 128->32
				-- width conversion internally, so there is no low/high
				-- split, no priming push, no trailing flush, and no
				-- CDC-settle wait -- all of which existed only to work
				-- around the old 64/32 FIFO's asymmetric-FWFT quirks and
				-- were a persistent source of intermittent corruption.
				case rd_pf_state is
					when 0 =>
						rd_pf_idle <= '1';
						-- rd_pf_issued < rd_pf_target is the per-batch
						-- command budget; ddr3_read_full = '0' is the
						-- overflow guard (a write-side ui_clk single-bit
						-- flag, natively safe to read from this domain).
						if ddr3_read_full = '0' and rd_pf_issued < rd_pf_target then
							wr_rd_app_addr <= rd_pf_addr;
							wr_rd_app_cmd  <= "001";
							wr_rd_app_en   <= '1';
							rd_pf_state  <= 1;
						end if;
					when 1 =>
						-- Assert app_en ONLY while the command has not yet
						-- been accepted -- deasserting it the cycle app_rdy
						-- accepts prevents MIG from latching the same read
						-- twice (the double-issue bug). Matches ramtester's
						-- s_read_1. NOTE: the address advance and command
						-- count are NOT done here -- they are committed on
						-- VALID in state 2, so a command MIG counts as
						-- accepted but never completes (the lost-command
						-- issue) can be retried at the same address.
						if mig_app_rdy = '1' then
							rd_pf_state    <= 2;
							rd_pf_wait_ctr <= 0;
						else
							wr_rd_app_addr <= rd_pf_addr;
							wr_rd_app_cmd  <= "001";
							wr_rd_app_en   <= '1';
						end if;
					when others => -- 2: wait for the response (with a
						-- lost-command timeout), push it whole, then commit.
						if mig_app_rd_data_valid = '1' then
							ddr3_read_din   <= mig_app_rd_data;
							ddr3_read_wr_en <= '1';
							rd_pf_addr      <= rd_pf_addr + 8;
							rd_pf_issued    <= rd_pf_issued + 1;
							dbg_cmd_count   <= dbg_cmd_count + 1;
							dbg_cmd_addr    <= rd_pf_addr;
							rd_pf_state     <= 0;
							-- DIAGNOSTIC: raw high-32 of the first two
							-- responses (WireOut 0x32/0x33).
							if dbg_resp_count = 0 then
								dbg_high0 <= mig_app_rd_data(127 downto 96);
							elsif dbg_resp_count = 1 then
								dbg_high1 <= mig_app_rd_data(127 downto 96);
							end if;
							dbg_resp_count <= dbg_resp_count + 1;
							-- DIAGNOSTIC: duplicate-response detector.
							if mig_app_rd_data = dbg_prev_rd_data then
								dbg_dup_count  <= dbg_dup_count + 1;
								dbg_dup_at_cmd <= "00000000" & dbg_cmd_count;
								if dbg_cmd_addr = dbg_prev_addr then
									dbg_dup_addr_match <= '1';
								else
									dbg_dup_addr_match <= '0';
								end if;
							end if;
							dbg_prev_rd_data <= mig_app_rd_data;
							dbg_prev_addr    <= dbg_cmd_addr;
						elsif rd_pf_wait_ctr = 2047 then
							-- lost command: MIG counted app_rdy but never
							-- returned a valid. Re-issue the SAME address
							-- (rd_pf_addr was not advanced). See
							-- rd_pf_wait_ctr declaration comment.
							dbg_retry_count <= dbg_retry_count + 1;
							rd_pf_state     <= 0;
						else
							rd_pf_wait_ctr <= rd_pf_wait_ctr + 1;
						end if;
				end case;
			end if;
		end if;
	end process;

	-- Phase 6a: MIG owns sys_clk_p/sys_clk_n directly (System Clock =
	-- Differential) -- no more IBUFGDS/sys_clk in this file, see file
	-- header comment. Phase 6b: app_* command/write-data interface now
	-- driven by the write-assembler/read-prefetch process above;
	-- app_wdf_end/app_wdf_mask tied to constants since this design only
	-- ever does single-beat, full-width-write bursts (see mig_app_*
	-- signal declaration comments).
	ddr3_inst : ddr3_256_16 port map (
		ddr3_dq             => ddr3_dq,
		ddr3_dqs_p          => ddr3_dqs_p,
		ddr3_dqs_n          => ddr3_dqs_n,
		ddr3_addr           => ddr3_addr,
		ddr3_ba             => ddr3_ba,
		ddr3_ras_n          => ddr3_ras_n,
		ddr3_cas_n          => ddr3_cas_n,
		ddr3_we_n           => ddr3_we_n,
		ddr3_reset_n        => ddr3_reset_n,
		ddr3_ck_p           => ddr3_ck_p,
		ddr3_ck_n           => ddr3_ck_n,
		ddr3_cke            => ddr3_cke,
		ddr3_dm             => ddr3_dm,
		ddr3_odt            => ddr3_odt,

		app_addr            => mig_app_addr,
		app_cmd             => mig_app_cmd,
		app_en              => mig_app_en,
		app_wdf_data        => mig_app_wdf_data,
		app_wdf_end         => '1',
		app_wdf_mask        => (others => '0'),
		app_wdf_wren        => mig_app_wdf_wren,
		app_rd_data         => mig_app_rd_data,
		app_rd_data_end     => open,
		app_rd_data_valid   => mig_app_rd_data_valid,
		app_rdy             => mig_app_rdy,
		app_wdf_rdy         => mig_app_wdf_rdy,
		app_sr_req          => '0',
		app_ref_req         => '0',
		app_zq_req          => '0',
		app_sr_active       => open,
		app_ref_ack         => open,
		app_zq_ack          => open,
		ui_clk              => ui_clk,
		ui_clk_sync_rst     => ui_clk_sync_rst,
		init_calib_complete => init_calib_complete,
		sys_clk_p           => sys_clk_p,
		sys_clk_n           => sys_clk_n,
		device_temp         => open,
		sys_rst             => mig_sys_rst
	);

	ddr3_write_fifo_inst : ddr3_write_fifo port map (
		rst    => '0',
		wr_clk => clk_100,
		rd_clk => ui_clk,
		din    => ddr3_write_din,
		wr_en  => ddr3_write_wr_en,
		rd_en  => ddr3_write_rd_en,
		dout   => ddr3_write_dout,
		full   => ddr3_write_full,
		empty  => ddr3_write_empty,
		rd_data_count => ddr3_write_rd_data_count
	);

	ddr3_read_fifo_inst : ddr3_read_fifo port map (
		rst    => ddr3_read_fifo_rst,
		wr_clk => ui_clk,
		rd_clk => okClk,
		din    => ddr3_read_din,
		wr_en  => ddr3_read_wr_en,
		rd_en  => ddr3_read_rd_en,
		dout   => ddr3_read_dout,
		full   => ddr3_read_full,
		empty  => ddr3_read_empty,
		rd_data_count => ddr3_read_rd_data_count,
		wr_data_count => ddr3_read_wr_data_count
	);

	-- MIG sys_rst pulse generation, see mig_sys_rst declaration comment.
	process (okClk)
	begin
		if rising_edge(okClk) then
			mig_sys_rst <= '0';
			-- BTPipeOut 0xA3 ep_ready: assert once at least one 16-byte
			-- block (4 read-side 32-bit words) is available, matching
			-- ramtester's pipe_out_ready. Registered in okClk.
			if ddr3_read_rd_data_count >= 4 then
				ddr3_read_pipe_ready <= '1';
			else
				ddr3_read_pipe_ready <= '0';
			end if;
		end if;
	end process;

	clk_gen : clk_wiz_0 port map (
		clk_in1  => ui_clk,
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

	okWO : okWireOR generic map (N => 27) port map (okEH => okEH, okEHx => okEHx);

	-- WireIn endpoints
	wi00 : okWireIn port map (okHE => okHE, ep_addr => x"00", ep_dataout => ep00wire);
	wi01 : okWireIn port map (okHE => okHE, ep_addr => x"01", ep_dataout => ep01wire);
	wi02 : okWireIn port map (okHE => okHE, ep_addr => x"02", ep_dataout => ep02wire);
	wi03 : okWireIn port map (okHE => okHE, ep_addr => x"03", ep_dataout => ep03wire);
	wi04 : okWireIn port map (okHE => okHE, ep_addr => x"04", ep_dataout => ep04wire);
	wi05 : okWireIn port map (okHE => okHE, ep_addr => x"05", ep_dataout => ep05wire);
	wi06 : okWireIn port map (okHE => okHE, ep_addr => x"06", ep_dataout => ep06wire);
	-- Phase 6b: per-batch read-command budget, see rd_pf_issued/
	-- rd_pf_target declaration comment.
	wi07 : okWireIn port map (okHE => okHE, ep_addr => x"07", ep_dataout => ep07wire);

	-- Phase 5 (PMT) m2: normal-mode counting control/config.
	wi08 : okWireIn port map (okHE => okHE, ep_addr => x"08", ep_dataout => ep08wire);
	wi09 : okWireIn port map (okHE => okHE, ep_addr => x"09", ep_dataout => ep09wire);
	wi0A : okWireIn port map (okHE => okHE, ep_addr => x"0A", ep_dataout => ep0Awire);

	-- TriggerIn endpoint
	-- Phase 6a: ep_clk moved from sys_clk to ui_clk, see file header comment.
	tr40 : okTriggerIn port map (okHE => okHE, ep_addr => x"40", ep_clk => ui_clk, ep_trigger => ep40wire);

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

	-- WireOut endpoints (Phase 5a sequencer bring-up, see file header comment)
	wo2B : okWireOut port map (okHE => okHE, okEH => okEHx(16*65-1 downto 15*65), ep_addr => x"2B", ep_datain => ep2Bwire);
	wo2C : okWireOut port map (okHE => okHE, okEH => okEHx(17*65-1 downto 16*65), ep_addr => x"2C", ep_datain => ep2Cwire);

	-- WireOut endpoint (Phase 6a MIG bring-up, see file header comment)
	wo2D : okWireOut port map (okHE => okHE, okEH => okEHx(18*65-1 downto 17*65), ep_addr => x"2D", ep_datain => ep2Dwire);

	-- WireOut endpoints (Phase 6b DDR3 write/read adapter bring-up, see file header comment)
	wo2E : okWireOut port map (okHE => okHE, okEH => okEHx(19*65-1 downto 18*65), ep_addr => x"2E", ep_datain => ep2Ewire);
	wo2F : okWireOut port map (okHE => okHE, okEH => okEHx(20*65-1 downto 19*65), ep_addr => x"2F", ep_datain => ep2Fwire);

	-- BTPipeOut endpoint (Phase 6b DDR3 read-prefetch readback, see file header comment)
	poA3 : okBTPipeOut port map (
		okHE => okHE, okEH => okEHx(21*65-1 downto 20*65), ep_addr => x"A3",
		ep_read => ddr3_read_rd_en, ep_blockstrobe => open, ep_datain => ddr3_read_dout, ep_ready => ddr3_read_pipe_ready
	);

	-- WireOut endpoint (0x30) -- DIAGNOSTIC (temporary), see
	-- dbg_valid_count declaration comment.
	wo30 : okWireOut port map (okHE => okHE, okEH => okEHx(22*65-1 downto 21*65), ep_addr => x"30", ep_datain => ep30wire);
	wo31 : okWireOut port map (okHE => okHE, okEH => okEHx(23*65-1 downto 22*65), ep_addr => x"31", ep_datain => ep31wire);
	wo32 : okWireOut port map (okHE => okHE, okEH => okEHx(24*65-1 downto 23*65), ep_addr => x"32", ep_datain => ep32wire);
	wo33 : okWireOut port map (okHE => okHE, okEH => okEHx(25*65-1 downto 24*65), ep_addr => x"33", ep_datain => ep33wire);
	wo34 : okWireOut port map (okHE => okHE, okEH => okEHx(26*65-1 downto 25*65), ep_addr => x"34", ep_datain => ep34wire);
	wo35 : okWireOut port map (okHE => okHE, okEH => okEHx(27*65-1 downto 26*65), ep_addr => x"35", ep_datain => ep35wire);

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
