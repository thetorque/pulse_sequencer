"""
sequence.py -- TTL pulse-sequence compiler (py3 port of servers/pulser/sequence.py).

Builds a sequence from human units (channel index, seconds) and compiles it to
the 2026 64-bit line list that Driver.load_program consumes. Compared to the
legacy version this:
  * drops LabRAD/numpy and the `parent` (DDS) coupling -- pure Python, so it is
    unit-testable off the bench (no `ok`, no hardware);
  * emits 64-bit line ints via wiremap.line() instead of the XEM6010 pipe byte
    packing (the driver's write path handles pipe byte order);
  * keeps the legacy timing model exactly: time is an ABSOLUTE, cumulative tick
    (40 ns), the first line's channel is the initial state, and the sequence
    ends with an all-zero terminator.

DDS programming (parseDDS/addToProgram) is NOT ported here -- that is M4,
deferred until the 2026 DDS hardware is ready.
"""
from decimal import Decimal

from .wiremap import line, TIME_RESOLUTION_S, TIME_MASK


class SequenceError(Exception):
    pass


class Sequence:
    """A TTL-only pulse sequence.

    channel_total     number of TTL channels (bit index 0..N-1 -> line bit i)
    time_resolution_s tick length in seconds (40 ns on this hardware)
    max_switches      cap on distinct switching times (FPGA program depth guard)
    """

    def __init__(self, channel_total=32,
                 time_resolution_s=TIME_RESOLUTION_S,
                 max_switches=1022,
                 channel_map=None):
        self.channel_total = channel_total
        self.time_resolution = Decimal(str(time_resolution_s))
        self.max_switches = max_switches
        self.max_step = TIME_MASK   # 31-bit absolute-time field
        # optional {name: number} so add_pulse accepts channel names; None = ints only
        self.channel_map = channel_map
        # timestep -> list of per-channel deltas in {-1, 0, +1}
        self.switching_times = {0: [0] * channel_total}
        self.switches = 1          # number of distinct switching times used

    def _resolve(self, channel):
        """Map a channel name (if a channel_map was given) to its int index."""
        if isinstance(channel, str):
            if not self.channel_map or channel not in self.channel_map:
                raise SequenceError(f"unknown channel name {channel!r}")
            return self.channel_map[channel]
        return channel

    # ---- building ----------------------------------------------------------
    def sec_to_step(self, sec):
        """Convert seconds to an absolute tick, rounded to the resolution."""
        start = Decimal('{0:.9f}'.format(sec))       # round to ns
        step = int((start / self.time_resolution).to_integral_value())
        if not 0 <= step <= self.max_step:
            raise SequenceError(
                f"time {sec}s -> step {step} out of range 0..{self.max_step} "
                f"(31-bit tick field, ~86 s max)")
        return step

    def add_pulse(self, channel, start_s, duration_s):
        """Add a TTL pulse on `channel` (int index, or a name if a channel_map
        was provided): ON at start, OFF after duration. Times in seconds."""
        channel = self._resolve(channel)
        if not 0 <= channel < self.channel_total:
            raise SequenceError(f"channel {channel} out of range "
                                f"0..{self.channel_total - 1}")
        start = self.sec_to_step(start_s)
        duration = self.sec_to_step(duration_s)
        if duration < 1:
            raise SequenceError("duration shorter than one tick (40 ns)")
        self._add_switch(start, channel, 1)
        self._add_switch(start + duration, channel, -1)

    def extend_length(self, time_s):
        """Extend the total sequence length to at least time_s (no-op switch)."""
        self._add_switch(self.sec_to_step(time_s), 0, 0)

    def _add_switch(self, step, channel, value):
        if step in self.switching_times:
            if value and self.switching_times[step][channel]:
                raise SequenceError(
                    f"double switch at step {step} for channel {channel}")
            self.switching_times[step][channel] = value
        else:
            if self.switches == self.max_switches:
                raise SequenceError(
                    f"exceeded maximum number of switches ({self.max_switches})")
            self.switching_times[step] = [0] * self.channel_total
            self.switches += 1
            self.switching_times[step][channel] = value

    # ---- compiling ---------------------------------------------------------
    def to_lines(self):
        """Compile to the 64-bit line list (terminator included). The first
        line (step 0) is the initial channel state; each later line applies its
        accumulated state at its absolute tick; a final all-zero terminator
        ends the run."""
        if len(self.switching_times) < 2:
            # only the initial {0: all-off} entry -> [line(0,0), terminator],
            # whose line[1] terminator gives time_stamp 0 at S_P1CAP and the
            # tick engine never matches -> the sequencer hangs. Refuse it.
            raise SequenceError(
                "empty sequence: add at least one pulse (or extend_length) "
                "before compiling")
        lines = []
        state = [0] * self.channel_total
        for step in sorted(self.switching_times):
            deltas = self.switching_times[step]
            channel_int = 0
            for i in range(self.channel_total):
                state[i] += deltas[i]
                if state[i] < 0:
                    raise SequenceError(
                        f"channel {i} switched off while already off "
                        f"(at step {step})")
                if state[i] > 1:
                    raise SequenceError(
                        f"overlapping pulses on channel {i} (at step {step})")
                if state[i]:
                    channel_int |= (1 << i)
            lines.append(line(step, channel_int))
        lines.append(0)   # all-zero terminator
        return lines

    def human_readable(self):
        """List of (time_seconds, channel_int, 'bit-string') for debugging,
        one row per switching time (terminator excluded)."""
        rows = []
        state = [0] * self.channel_total
        for step in sorted(self.switching_times):
            for i, d in enumerate(self.switching_times[step]):
                state[i] += d
            channel_int = sum((1 << i) for i in range(self.channel_total) if state[i])
            bits = ''.join('1' if state[i] else '0'
                           for i in range(self.channel_total))   # LSB (ch0) first
            rows.append((step * float(self.time_resolution), channel_int, bits))
        return rows
