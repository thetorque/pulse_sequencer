"""
wiremap.py -- the XEM7305 (2026) pulser endpoint map.

Single source of truth for the host<->FPGA contract of the 2026 bitstream
(photon.vhd, Phase 6c). This is the map the driver drives; it is DELIBERATELY
different from the legacy XEM6010 map in ../servers/pulser/api.py, and the whole
point of the py3 port is to target this column instead of that one.

Pure constants -- no `ok`, no hardware -- so it imports on any machine and the
sequence compiler / unit tests can depend on it off the bench.

Cross-checked against the known-good test scripts:
  VHDL_files/XEM7305_Pulser_2026_09_07/test/ddr3_sequencer_bringup.py
  VHDL_files/XEM7305_Pulser_2026_09_07/test/ddr3_roundtrip_demo.py
"""

# ---- WireIn 0x00 (ep00wire): control bits ---------------------------------
# NOTE: absolute bit positions, unlike the legacy 0x00 map (start=0x04 etc.).
EP_CONTROL = 0x00
INFINITE_BIT = 1 << 1   # ep00wire(1): pulser_infinite_loop
START_BIT    = 1 << 2   # ep00wire(2): pulser_start_bit (rising edge starts a run)
LINETRIG_BIT = 1 << 3   # ep00wire(3): line-trigger enable (sim-proven, not HW-tested)
READMODE_BIT = 1 << 4   # ep00wire(4): 0 = DDR3 write mode, 1 = read mode
SEQMODE_BIT  = 1 << 5   # ep00wire(5): 1 = DDR3 sequencer, 0 = legacy pulser_ram

# ---- WireIn 0x05 (ep05wire): finite-loop limit ----------------------------
EP_LOOP_LIMIT = 0x05    # 16-bit: 0 = unlimited (with INFINITE_BIT), N = stop after N

# ---- TriggerIn 0x40: resets ------------------------------------------------
TRIG_RESET = 0x40
TRIG_RESET_BIT = 0      # bit 0: pulser_counter_reset (resets sequencer FSM + counters)

# ---- WireOut status --------------------------------------------------------
WO_LOGIC      = 0x2B    # ep2Bwire: logic_out (== master_logic when override mux off)
WO_SEQ        = 0x2C    # ep2Cwire: bit16 seq_done, bits[15:0] seq_count, bit17 drop/overflow
WO_CALIB      = 0x2D    # ep2Dwire: bit0 MIG init_calib_complete
WO_LINE_COUNT = 0x35    # ep35wire: 32-bit count of lines the sequencer popped this run

SEQ_DONE_BIT   = 1 << 16
SEQ_COUNT_MASK = 0xFFFF
SEQ_OVERFLOW_BIT = 1 << 17   # streamer FIFO-overflow / dropped-beat sticky flag

CALIB_COMPLETE_BIT = 1

# ---- PMT normal-mode photon counting (Phase 5 m2) --------------------------
# The counter runs on clk_100 (100 MHz): gate/period are in clk_100 cycles.
EP_PMT_CTRL   = 0x08    # WireIn: bit0 = counter enable, bit1 = use synthetic source
EP_PMT_PERIOD = 0x09    # WireIn: synthetic-source period (clk_100 cycles per pulse)
EP_PMT_GATE   = 0x0A    # WireIn: collection gate length (clk_100 cycles per window)
PMT_COUNT_EN_BIT = 1 << 0
PMT_SIM_EN_BIT   = 1 << 1

WO_PMT_FILL   = 0x29    # WireOut: normal_pmt_fifo fill level (readable words, bits 9:0)
PMT_FILL_MASK = 0x3FF
PMT_PIPE      = 0xA1    # BTPipeOut: per-window counts (32-bit words)
# ep_ready is tied high on 0xA0/A1/A2 in this bitstream -> read ONLY whole
# 16-byte (4-word) blocks that WO_PMT_FILL reports are present.
PMT_PIPE_BLOCK = 16     # bytes
PMT_PIPE_WORDS_PER_BLOCK = PMT_PIPE_BLOCK // 4

TRIG_PMT_FIFO_RESET_BIT = 2   # TriggerIn 0x40 bit2: normal_pmt_fifo reset (legacy resetFIFONormal)

CLK_100_HZ = 100_000_000      # counting clock; converts gate/period cycles <-> seconds/Hz

# ---- PMT differential (sequence-gated) counting (Phase 5 m4d) ---------------
# Differential mode (ep08 bit3): normal_pmt_fifo is fed by the sequence-gated
# counter instead of the free-running one. Each count word carries the 866
# state in bit31 (1 = 866 was OFF), count in bits[30:0] -- legacy infoFromBuf.
# The window is gated by the running program's channel 16 (DiffCountTrigger);
# the 866 state is its channel 0.
PMT_DIFF_MODE_BIT  = 1 << 3    # WireIn 0x08 bit3: 1 = differential mode
PMT_STATUS_OFF_BIT = 1 << 31   # count word bit31: 1 = 866 was OFF, 0 = ON
PMT_COUNT_MASK     = 0x7FFFFFFF  # count word bits[30:0]
CH_DIFF_TRIGGER = 16          # sequence channel that gates differential windows
CH_866          = 0           # sequence channel carrying the 866/repump state

# ---- PMT time-resolved timetagging (Phase 5 m4b) ---------------------------
# The timetagger runs on clk_200 (200 MHz) = fifo_photon's wr_clk, so each
# timestamp tick is 5 ns (finer than the legacy 10 ns timeResolvedResolution).
PMT_RECORD_EN_BIT = 1 << 2    # WireIn 0x08 bit2: record photon timestamps (detection window)
WO_PHOTON_FILL    = 0x28      # WireOut: fifo_photon fill level (readable words, bits 14:0)
PHOTON_FILL_MASK  = 0x7FFF
PHOTON_PIPE       = 0xA0      # BTPipeOut: photon timestamps (32-bit words, 5 ns ticks)
TRIG_PHOTON_FIFO_RESET_BIT = 3   # TriggerIn 0x40 bit3: fifo_photon reset
TIMETAG_RESOLUTION_S = 5.0e-9    # 1 timestamp tick = 5 ns (clk_200)

# ---- Program-line format ---------------------------------------------------
# 64-bit line: channel = bits[31:0], time = bits[62:32] (31-bit absolute tick,
# ~86 s max), bit63 reserved. 1 tick = 40 ns. See pulse-sequence-ram-format memo.
TIME_MASK = 0x7FFFFFFF          # 31-bit absolute-time field
CHANNEL_MASK = 0xFFFFFFFF
TICKS_PER_SEC = 25_000_000      # 1 / 40 ns
TIME_RESOLUTION_S = 40.0e-9

# Streamer PRIME_BEATS=8 -> 16 lines primed before ready; pad every program to
# this (with terminators) so the primed window is never stale DDR3 content.
PRIME_LINES = 16


def line(time_ticks, channel):
    """Pack one 64-bit pulse line (time in ticks, channel bitmask)."""
    return ((time_ticks & TIME_MASK) << 32) | (channel & CHANNEL_MASK)
