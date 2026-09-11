"""
driver.py -- headless Python-3 low-level driver for the XEM7305 pulser.

This is the port of the FPGA-facing half of the legacy XEM6010 driver
(../servers/pulser/api.py) onto the 2026 bitstream's endpoint map (wiremap.py).
It has NO LabRAD / Twisted / Qt dependency -- just `ok` (the FrontPanel module)
and the proven DDR3 pipe primitives (via _ddr3.py).

Legacy -> 2026 highlights (see wiremap.py for the full table):
  * program store is DDR3, not on-chip pulser_ram (upload still via BTPipeIn 0x80)
  * control moved to absolute ep00 bits (START=bit2, INFINITE=bit1, SEQMODE=bit5)
  * reset is TriggerIn 0x40 bit0 (was bit1 "resetRam")
  * status: seq_done = WireOut 0x2C bit16, seq_count = bits[15:0], line_count = 0x35

Normal-mode PMT photon counting IS ported (the datapath exists in the 2026
bitstream, Phase 5 m2, fed by an on-FPGA synthetic source for bring-up). DDS,
Differential (sequence-gated) counting, and time-resolved timetagging are not
ported yet -- see README.md "Deferred (M4)".
"""
import struct
import time

from . import wiremap as W
from . import _ddr3


class PulserError(Exception):
    pass


class Driver:
    """Low-level control of one XEM7305 running the 2026 pulser bitstream."""

    def __init__(self):
        self.xem = None

    # ---- connection --------------------------------------------------------
    def connect(self, bit_path):
        """Open the device, ConfigureFPGA(bit_path), wait for DDR3 calibration."""
        self.xem = _ddr3.connect(bit_path)
        return self.xem

    def _check(self):
        if self.xem is None:
            raise PulserError("FPGA not connected -- call connect(bit_path) first")

    # ---- raw wire helpers --------------------------------------------------
    def _set_ep00(self, value):
        """Drive ep00wire to an absolute value (all bits) and commit."""
        self.xem.SetWireInValue(W.EP_CONTROL, value, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def _read(self, wire):
        self.xem.UpdateWireOuts()
        return self.xem.GetWireOutValue(wire)

    def reset(self):
        """Pulse the sequencer/counter reset (TriggerIn 0x40 bit0)."""
        self._check()
        self.xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_RESET_BIT)

    # ---- program upload ----------------------------------------------------
    @staticmethod
    def pad_program(lines):
        """Return `lines` guaranteed terminated and padded for the streamer:
        a trailing all-zero terminator, then zero-padding up to PRIME_LINES and
        to an even count (extra terminators are inert -- see the RAM-format memo).
        """
        prog = list(lines)
        if not prog or prog[-1] != 0:
            prog.append(0)                      # terminator -> seq_done
        while len(prog) < W.PRIME_LINES or len(prog) % 2 != 0:
            prog.append(0)
        return prog

    def load_program(self, lines, verify=True):
        """Pad, then write the program to DDR3 @ address 0. If verify, read the
        low (cold-start-immune) words back and confirm they match before trusting
        the streamer. Returns the padded program actually written."""
        self._check()
        prog = self.pad_program(lines)
        _ddr3.reset_ddr3(self.xem)
        _ddr3.write_words(self.xem, prog)
        if verify:
            n = min(len(prog), 4096)            # stay within the immune low 32 KiB
            got = _ddr3.read_words(self.xem, n)
            if got != prog[:n]:
                bad = next(i for i, (w, r) in enumerate(zip(prog, got)) if w != r)
                raise PulserError(
                    f"DDR3 write-verify mismatch at line {bad}: "
                    f"wrote {prog[bad]:#018x}, read {got[bad]:#018x}")
        return prog

    # ---- run control -------------------------------------------------------
    def _start(self, infinite, loop_limit):
        self._check()
        self.xem.SetWireInValue(W.EP_LOOP_LIMIT, loop_limit & 0xFFFF, 0xFFFFFFFF)
        self.xem.UpdateWireIns()
        base = W.SEQMODE_BIT | (W.INFINITE_BIT if infinite else 0)
        self._set_ep00(base)                    # enter DDR3-seq mode, start off
        self.reset()                            # reset the sequencer FSM
        self._set_ep00(base | W.START_BIT)      # rising START -> prime + run

    def start_single(self):
        """Run the loaded program once."""
        self._start(infinite=False, loop_limit=0)

    def start_infinite(self):
        """Run the loaded program, looping forever (until stop())."""
        self._start(infinite=True, loop_limit=0)

    def start_number(self, repetitions):
        """Run the loaded program a finite number of times."""
        if not 1 <= repetitions <= 0xFFFF:
            raise PulserError("repetitions must be in 1..65535")
        self._start(infinite=True, loop_limit=repetitions)

    def stop(self):
        """Stop any running sequence and clear all control bits."""
        self._check()
        self._set_ep00(0)
        self.reset()

    # ---- status ------------------------------------------------------------
    def is_done(self):
        return bool(self._read(W.WO_SEQ) & W.SEQ_DONE_BIT)

    def seq_count(self):
        """Completed iterations (infinite/number modes)."""
        return self._read(W.WO_SEQ) & W.SEQ_COUNT_MASK

    def overflow(self):
        """True if the streamer dropped a beat this run (FIFO overflow)."""
        return bool(self._read(W.WO_SEQ) & W.SEQ_OVERFLOW_BIT)

    def line_count(self):
        """Lines the sequencer popped this run (integrity check)."""
        return self._read(W.WO_LINE_COUNT)

    def logic_out(self):
        """Current TTL output word (master_logic, WireOut 0x2B)."""
        return self._read(W.WO_LOGIC)

    def wait_done(self, timeout=90.0, poll=0.05):
        """Block until seq_done or timeout. Returns True if done in time."""
        self._check()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_done():
                return True
            time.sleep(poll)
        return False

    # ---- PMT normal-mode photon counting -----------------------------------
    # The counter (pmt_counter) tallies rising edges over a collection gate and
    # pushes one count per closed window into normal_pmt_fifo (read over pipe
    # 0xA1). For bring-up the input is an on-FPGA synthetic source (pmt_sim) at
    # a known rate; the real detector wires into the same mux later. Ports the
    # legacy getNormalTotal/getNormalCounts/resetFIFONormal onto the 2026 map.

    @staticmethod
    def seconds_to_cycles(seconds):
        """Collection time (s) -> clk_100 cycles for the gate length."""
        return round(seconds * W.CLK_100_HZ)

    @staticmethod
    def rate_to_period(rate_hz):
        """Synthetic-source rate (Hz) -> clk_100 cycles between pulses."""
        return round(W.CLK_100_HZ / rate_hz)

    def pmt_reset_fifo(self):
        """Clear normal_pmt_fifo (legacy resetFIFONormal)."""
        self._check()
        self.xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_PMT_FIFO_RESET_BIT)

    def pmt_configure(self, gate_cycles, period_cycles=0):
        """Set the collection gate length and (for the synthetic source) the
        pulse period, both in clk_100 cycles. See seconds_to_cycles/rate_to_period."""
        self._check()
        self.xem.SetWireInValue(W.EP_PMT_GATE, gate_cycles & 0xFFFFFFFF, 0xFFFFFFFF)
        self.xem.SetWireInValue(W.EP_PMT_PERIOD, period_cycles & 0xFFFFFFFF, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def pmt_start(self, synthetic=True):
        """Begin periodic counting. synthetic=True drives the on-FPGA source;
        False selects the real detector input (all-zero until a pin is wired)."""
        self._check()
        ctrl = W.PMT_COUNT_EN_BIT | (W.PMT_SIM_EN_BIT if synthetic else 0)
        self.xem.SetWireInValue(W.EP_PMT_CTRL, ctrl, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def pmt_stop(self):
        """Stop counting (freezes the FIFO fill so a readout is stable)."""
        self._check()
        self.xem.SetWireInValue(W.EP_PMT_CTRL, 0, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def pmt_available(self):
        """Windows currently in normal_pmt_fifo (legacy getNormalTotal)."""
        return self._read(W.WO_PMT_FILL) & W.PMT_FILL_MASK

    def pmt_read_counts(self, n=None):
        """Read per-window counts from normal_pmt_fifo (legacy getNormalCounts).
        Reads only whole 16-byte blocks that are actually present (0xA1's
        ep_ready is tied high -- reading past the fill would return stale data),
        so the result may be up to 3 words short of `n`; stop counting first for
        a stable fill. Returns a list of 32-bit counts."""
        self._check()
        avail = self.pmt_available()
        n = avail if n is None else min(n, avail)
        n -= n % W.PMT_PIPE_WORDS_PER_BLOCK          # whole blocks only
        if n == 0:
            return []
        buf = bytearray(n * 4)
        got = self.xem.ReadFromBlockPipeOut(W.PMT_PIPE, W.PMT_PIPE_BLOCK, buf)
        if got != len(buf):
            raise PulserError(f"PMT pipe read returned {got}, expected {len(buf)}")
        return list(struct.unpack(f"<{n}I", bytes(buf)))

    # ---- PMT time-resolved timetagging -------------------------------------
    # The timetagger records each photon's arrival TIME (5 ns ticks, clk_200)
    # into fifo_photon (pipe 0xA0) while record_en is high -- the detection
    # window. Ports the legacy getTimetags/getResolvedTotal/resetTimetags onto
    # the 2026 map. Independent of the normal counter above (different FIFO/
    # pipe), though both share the synthetic source and ep08.

    @staticmethod
    def ticks_to_seconds(ticks):
        """Timestamp ticks -> seconds (5 ns each, clk_200)."""
        return ticks * W.TIMETAG_RESOLUTION_S

    def pmt_timetag_reset(self):
        """Clear fifo_photon (legacy resetTimetags)."""
        self._check()
        self.xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_PHOTON_FIFO_RESET_BIT)

    def pmt_record_start(self, synthetic=True, period_cycles=None):
        """Open the detection window: record photon timestamps. synthetic=True
        drives the on-FPGA source (set period_cycles, in clk_100 cycles, to pick
        its rate); False records the real detector input."""
        self._check()
        if period_cycles is not None:
            self.xem.SetWireInValue(W.EP_PMT_PERIOD, period_cycles & 0xFFFFFFFF, 0xFFFFFFFF)
        ctrl = W.PMT_RECORD_EN_BIT | (W.PMT_SIM_EN_BIT if synthetic else 0)
        self.xem.SetWireInValue(W.EP_PMT_CTRL, ctrl, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def pmt_record_stop(self):
        """Close the detection window (freezes the FIFO fill for a stable read)."""
        self._check()
        self.xem.SetWireInValue(W.EP_PMT_CTRL, 0, 0xFFFFFFFF)
        self.xem.UpdateWireIns()

    def pmt_timetags_available(self):
        """Photon timestamps currently in fifo_photon (legacy getResolvedTotal)."""
        return self._read(W.WO_PHOTON_FILL) & W.PHOTON_FILL_MASK

    def pmt_read_timetags(self, n=None):
        """Read photon timestamps from fifo_photon (legacy getTimetags). Like
        pmt_read_counts, reads only whole 16-byte blocks the fill wire reports
        (0xA0's ep_ready is tied high); stop recording first for a stable fill.
        Returns a list of 32-bit timestamps (multiply by TIMETAG_RESOLUTION_S,
        or use ticks_to_seconds, for seconds)."""
        self._check()
        avail = self.pmt_timetags_available()
        n = avail if n is None else min(n, avail)
        n -= n % W.PMT_PIPE_WORDS_PER_BLOCK          # whole blocks only
        if n == 0:
            return []
        buf = bytearray(n * 4)
        got = self.xem.ReadFromBlockPipeOut(W.PHOTON_PIPE, W.PMT_PIPE_BLOCK, buf)
        if got != len(buf):
            raise PulserError(f"photon pipe read returned {got}, expected {len(buf)}")
        return list(struct.unpack(f"<{n}I", bytes(buf)))
