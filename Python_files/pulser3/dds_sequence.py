"""
dds_sequence.py -- DDS pulses inside a pulse sequence (M4 part 2: the parseDDS port).

Py3 port of the legacy servers/pulser/sequence.py parseDDS/addToProgram plus the
server's addDDSPulses (servers/pulser/dds.py), retargeted to DDS_BUS_CONTRACT.md v0.3.

Model (unchanged from the legacy pulser)
----------------------------------------
Every DDS channel lives on one board and holds a table of rows. All boards step
TOGETHER on the broadcast STEPNEXT line (TTL 18, 'AdvanceDDS'), so every board gets
one row per "change time" -- any instant at which ANY channel's setting changes:

    row 0       the channel's current manual state (what it outputs between runs)
    row k (k>0) the channel's state from change time T[k-1] on
    AdvanceDDS  a 3-tick (120 ns) pulse at each T[k]   -> the board applies row k+1
    ResetDDS    a 3-tick pulse at the end of the sequence (RAMRESET, TTL 19)
                -> row pointer back to 0, i.e. the manual state

A DDS pulse = a 'start' entry (the pulse's row) + a 'stop' entry (the same
frequency/phase/amplitude with the RF switch OPEN -- contract decision 2; the
frequency is kept so the phase stays continuous, like the legacy coherent model).
Back-to-back pulses on one channel (stop == next start) are allowed, the start
wins; truly overlapping pulses on one channel are an error. Zero-length pulses
are ignored and frequency 0 means "off", both as in the legacy server.

New for the 2026 hardware
-------------------------
* min step spacing (contract decision 5): consecutive change times, the first
  change time (from the sequence start -- in a loop the previous iteration's
  ResetDDS sits just before it), and the last change -> ResetDDS all need >= 5 us;
  ResetDDS is pushed later if needed (the legacy put it 120 ns after the last step).
* amplitude is dBm through the channel's VgaCal; no ramps (decision 3) -- a
  non-zero ramp rate is rejected rather than silently dropped.
* table depth 8192 rows per board.

compile_sequence() never mutates the Sequence (it compiles a copy), so it can be
called again, e.g. after adding more pulses.
"""
import copy
from collections import defaultdict
from dataclasses import dataclass, field

from . import dds as D
from . import wiremap as W
from .dds import DDSError

RESET_STEP_TICKS = 3            # AdvanceDDS / ResetDDS pulse width (legacy resetstepDuration)
MIN_STEP_S = 5e-6               # contract decision 5
MIN_STEP_TICKS = round(MIN_STEP_S / W.TIME_RESOLUTION_S)   # 125 ticks @ 40 ns


@dataclass
class DDSChannel:
    """One DDS output: which board it is on, its limits/calibration and manual state.

    addr          backplane board address 0..30, or 31 (broadcast) for a lone bench
                  board whose address straps don't matter -- then it must be the
                  only channel
    frequency_mhz / amplitude_dbm / phase_deg / on
                  the manual (between-runs) state = row 0 of every program
    """
    name: str
    addr: int
    frequency_mhz: float = 100.0
    amplitude_dbm: float = -10.0
    phase_deg: float = 0.0
    on: bool = False
    freq_range_mhz: tuple = (0.1, 400.0)
    cal: D.VgaCal = field(default_factory=D.VgaCal)
    f_sysclk_hz: float = D.F_SYSCLK_HZ

    @property
    def amp_range_dbm(self):
        return (self.cal.min_dbm, self.cal.max_dbm)

    def check(self, frequency_mhz=None, amplitude_dbm=None):
        lo, hi = self.freq_range_mhz
        if frequency_mhz is not None and not lo <= frequency_mhz <= hi:
            raise DDSError(f"{self.name}: frequency {frequency_mhz} MHz outside {lo}..{hi} MHz")
        lo, hi = self.amp_range_dbm
        if amplitude_dbm is not None and not lo <= amplitude_dbm <= hi:
            raise DDSError(f"{self.name}: amplitude {amplitude_dbm} dBm outside {lo}..{hi} dBm")

    def row(self, frequency_mhz, amplitude_dbm, phase_deg=0.0, rf_on=True):
        self.check(frequency_mhz, amplitude_dbm)
        return D.Row(freq_hz=frequency_mhz * 1e6, phase_deg=phase_deg,
                     vga=self.cal.code(amplitude_dbm, frequency_mhz * 1e6),
                     rf_on=rf_on, f_sysclk_hz=self.f_sysclk_hz)

    def manual_row(self):
        """Row 0: the current manual state (legacy _channel_to_num)."""
        return self.row(self.frequency_mhz, self.amplitude_dbm, self.phase_deg, self.on)

    def off_row(self):
        """'Off' at the manual frequency (legacy off_parameters)."""
        return self.row(self.frequency_mhz, self.amplitude_dbm, self.phase_deg, False)


# ---------------------------------------------------------------------------
# building (legacy server addDDSPulses)
# ---------------------------------------------------------------------------
def add_dds_pulse(seq, channel, start_s, duration_s, frequency_mhz, amplitude_dbm,
                  phase_deg=0.0, ramp_rate_mhz=0.0, amp_ramp_rate_db=0.0):
    """Add one DDS pulse to `seq` (a pulser3 Sequence) on DDSChannel `channel`."""
    if ramp_rate_mhz or amp_ramp_rate_db:
        raise DDSError(f"{channel.name}: ramps are not supported on the 2026 DDS "
                       "(contract decision 3) -- use explicit steps")
    if not start_s > 0:
        # row 0 is the manual state; a change at t=0 would alter the output before
        # the sequence runs (legacy: "start can not be 0")
        raise DDSError(f"{channel.name}: DDS pulse must start after t=0 (got {start_s} s)")
    if duration_s < 0:
        raise DDSError(f"{channel.name}: negative duration {duration_s} s")
    if frequency_mhz == 0:
        on = off = channel.off_row()
    else:
        on = channel.row(frequency_mhz, amplitude_dbm, phase_deg, True)
        off = channel.row(frequency_mhz, amplitude_dbm, phase_deg, False)
    if seq.sec_to_step(duration_s) == 0:
        return                                    # 0-length pulses are ignored
    seq.add_dds(channel.name, start_s, on, 'start')
    seq.add_dds(channel.name, start_s + duration_s, off, 'stop')


# ---------------------------------------------------------------------------
# compiling (legacy parseDDS)
# ---------------------------------------------------------------------------
def build_table(entries, initial, min_step_ticks=MIN_STEP_TICKS, max_rows=D.N_ROWS):
    """entries [(name, tick, row, typ)] + initial {name: row0}
    -> (change_ticks, {name: [row0, row1, ...]}). Pure; no TTL side effects."""
    by_tick = defaultdict(list)
    for name, tick, row, typ in entries:
        if name not in initial:
            raise DDSError(f"unknown DDS channel {name!r} (configured: {sorted(initial)})")
        by_tick[tick].append((name, row, typ))
    ticks = sorted(by_tick)
    if not ticks:
        return [], {n: [r] for n, r in initial.items()}
    if ticks[0] < min_step_ticks:
        raise DDSError(f"first DDS change at {ticks[0] * W.TIME_RESOLUTION_S * 1e6:.3f} us; "
                       f"needs >= {min_step_ticks * W.TIME_RESOLUTION_S * 1e6:g} us after the "
                       "sequence start (the previous loop's ResetDDS)")
    for a, b in zip(ticks, ticks[1:]):
        if b - a < min_step_ticks:
            raise DDSError(f"DDS changes at {a * W.TIME_RESOLUTION_S * 1e6:.3f} us and "
                           f"{b * W.TIME_RESOLUTION_S * 1e6:.3f} us are closer than the "
                           f"{min_step_ticks * W.TIME_RESOLUTION_S * 1e6:g} us minimum step")
    if len(ticks) + 1 > max_rows:
        raise DDSError(f"{len(ticks) + 1} DDS rows exceed the {max_rows}-row table")

    state = dict(initial)
    active = dict.fromkeys(initial, False)
    rows = {n: [r] for n, r in initial.items()}
    for t in ticks:
        evs = by_tick[t]
        for name, row, typ in evs:                # stops first: back-to-back -> start wins
            if typ == 'stop':
                if not active[name]:
                    raise DDSError(f"{name}: pulse stop at tick {t} without a running pulse")
                active[name] = False
                state[name] = row
        for name, row, typ in evs:
            if typ == 'start':
                if active[name]:
                    raise DDSError(f"{name}: overlapping DDS pulses at "
                                   f"{t * W.TIME_RESOLUTION_S:.9f} s")
                active[name] = True
                state[name] = row
        for n in rows:
            rows[n].append(state[n])
    return ticks, rows


@dataclass
class DDSProgram:
    """Compiled DDS tables, ready to send over pipe 0x81."""
    channels: dict                     # name -> DDSChannel
    rows: dict                         # name -> [Row]
    ticks: list                        # change times (AdvanceDDS), 40 ns ticks
    reset_tick: int                    # ResetDDS

    @property
    def n_rows(self):
        return len(self.ticks) + 1

    def frames(self):
        """WRITE_ROWS for every board from row 0, then one broadcast RESET so each
        board sits on row 0 (the manual state) before the first run."""
        out = []
        for name, ch in self.channels.items():
            out += D.program_board(ch.addr, self.rows[name], start=0)
        return out + [D.reset()]

    def describe(self):
        """Human-readable table: [(time_s or None for row 0, {name: Row})]."""
        times = [None] + [t * W.TIME_RESOLUTION_S for t in self.ticks]
        return [(t, {n: self.rows[n][k] for n in self.rows}) for k, t in enumerate(times)]


def check_channels(channels):
    addrs = defaultdict(list)
    for name, ch in channels.items():
        if name != ch.name:
            raise DDSError(f"channel key {name!r} != DDSChannel.name {ch.name!r}")
        if not 0 <= ch.addr <= D.BROADCAST:
            raise DDSError(f"{name}: board address {ch.addr} outside 0..31")
        addrs[ch.addr].append(name)
    for a, names in addrs.items():
        if len(names) > 1:
            raise DDSError(f"channels {names} share board address {a}")
    if D.BROADCAST in addrs and len(channels) > 1:
        raise DDSError("a broadcast-address (31) channel must be the only DDS channel")


def compile_sequence(seq, channels, min_step_ticks=MIN_STEP_TICKS,
                     reset_ticks=RESET_STEP_TICKS):
    """Compile `seq` (TTL pulses + DDS entries) for the hardware.

    channels: {name: DDSChannel}, ALL configured channels (each gets a full table,
    as in the legacy server). Returns (ttl_lines, DDSProgram or None). The input
    Sequence is not modified.
    """
    if not seq.has_dds():
        return seq.to_lines(), None
    check_channels(channels)
    s = copy.deepcopy(seq)
    adv, rst = W.DDS_ADVANCE_CHANNEL, W.DDS_RESET_CHANNEL
    for t, deltas in s.switching_times.items():
        if deltas[adv] or deltas[rst]:
            raise DDSError("AdvanceDDS/ResetDDS (TTL 18/19) are driven by the DDS "
                           f"compiler; the sequence already switches them at tick {t}")
    initial = {n: ch.manual_row() for n, ch in channels.items()}
    ticks, rows = build_table(s.dds_entries, initial, min_step_ticks)
    for t in ticks:
        s._add_switch(t, adv, 1)
        s._add_switch(t + reset_ticks, adv, -1)
    reset_tick = max(max(s.switching_times), ticks[-1] + min_step_ticks)
    s._add_switch(reset_tick, rst, 1)
    s._add_switch(reset_tick + reset_ticks, rst, -1)
    s.dds_entries = []
    return s.to_lines(), DDSProgram(dict(channels), rows, ticks, reset_tick)


def bus_seconds(frames):
    """Upper estimate of the time the master needs to clock `frames` out on the
    backplane (25 MHz SCK = 320 ns/byte, + per-frame CS gap), x1.5 margin. The
    host must not start a sequence before its tables have landed."""
    nbytes = sum(len(f) for f in frames)
    return 1.5 * (nbytes * 0.36e-6 + len(frames) * 0.6e-6) + 2e-3
