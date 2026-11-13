#!/usr/bin/env python3
"""
Unit tests for pulser3.dds_sequence -- the parseDDS port. No hardware:

    python -m pulser3.test_dds_sequence     # (also discoverable by pytest)

Includes a line-for-line py3 transliteration of the legacy servers/pulser/sequence.py
parseDDS as a reference model; random pulse sets must give the same row tables and
AdvanceDDS times as the port.
"""
import random

from . import dds as D
from . import dds_sequence as DS
from . import hwconfig
from . import wiremap as W

TICK = W.TIME_RESOLUTION_S
ADV, RST = W.DDS_ADVANCE_CHANNEL, W.DDS_RESET_CHANNEL


def chans(*names_addrs):
    return {n: DS.DDSChannel(n, addr=a, frequency_mhz=100.0, amplitude_dbm=0.0, on=False)
            for n, a in names_addrs}


def pulses_on(lines, channel):
    """(on_tick, off_tick) pairs of `channel` in a compiled line list."""
    out, prev, t_on = [], 0, None
    for ln in lines[:-1]:
        t, ch = ln >> 32 & W.TIME_MASK, ln & 0xFFFFFFFF
        bit = ch >> channel & 1
        if bit and not prev:
            t_on = t
        if prev and not bit:
            out.append((t_on, t))
        prev = bit
    return out


def line_fields(ln):
    return ln >> 32 & W.TIME_MASK, ln & 0xFFFFFFFF


# ---------------------------------------------------------------------------
def test_line_layout_assumption():
    t, ch = line_fields(W.line(1234, 0x40001))
    assert (t, ch) == (1234, 0x40001)


def test_single_pulse():
    c = chans(("A", 3))
    seq = hwconfig.new_sequence()
    seq.add_pulse('ttl_0', 1e-3, 1e-3)
    DS.add_dds_pulse(seq, c["A"], 1e-3, 2e-3, 50.0, 0.0)
    lines, prog = DS.compile_sequence(seq, c)
    a = prog.rows["A"]
    assert len(a) == 3 and prog.n_rows == 3
    assert a[0] == c["A"].manual_row() and not a[0].rf_on
    assert a[1] == D.Row(50e6, 0.0, 0xB40, True)
    assert a[2] == D.Row(50e6, 0.0, 0xB40, False)          # stop: same tone, switch open
    assert prog.ticks == [25_000, 75_000]
    assert pulses_on(lines, ADV) == [(25_000, 25_003), (75_000, 75_003)]
    # ResetDDS: >= 5 us after the last change even though nothing else follows it
    assert pulses_on(lines, RST) == [(75_125, 75_128)]
    assert pulses_on(lines, 0) == [(25_000, 50_000)]       # user TTL untouched


def test_reset_at_end_of_long_ttl():
    c = chans(("A", 3))
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, c["A"], 1e-3, 1e-3, 50.0, 0.0)
    seq.extend_length(10e-3)
    lines, prog = DS.compile_sequence(seq, c)
    assert pulses_on(lines, RST) == [(250_000, 250_003)]   # legacy: at the last TTL time


def test_compile_does_not_mutate_and_is_repeatable():
    c = chans(("A", 3))
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, c["A"], 1e-3, 1e-3, 50.0, 0.0)
    before = (dict((k, list(v)) for k, v in seq.switching_times.items()), list(seq.dds_entries))
    l1, p1 = DS.compile_sequence(seq, c)
    l2, p2 = DS.compile_sequence(seq, c)
    assert l1 == l2 and p1.rows == p2.rows
    assert (dict((k, list(v)) for k, v in seq.switching_times.items()), seq.dds_entries) == before


def test_two_boards_step_together():
    c = chans(("A", 1), ("B", 2))
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, c["A"], 10e-6, 20e-6, 50.0, 0.0)     # 10..30 us
    DS.add_dds_pulse(seq, c["B"], 20e-6, 20e-6, 70.0, -5.0)    # 20..40 us
    _, prog = DS.compile_sequence(seq, c)
    assert prog.ticks == [250, 500, 750, 1000]
    A, B = prog.rows["A"], prog.rows["B"]
    assert len(A) == len(B) == 5
    assert [r.rf_on for r in A] == [False, True, True, False, False]
    assert [r.rf_on for r in B] == [False, False, True, True, False]
    assert A[1].freq_hz == 50e6 and B[2].freq_hz == 70e6 and B[2].vga == c["B"].cal.code(-5.0)
    fr = prog.frames()
    assert [f[:2] for f in fr] == [bytes([1, 1]), bytes([2, 1]), bytes([0x1F, 2])]
    assert all(f[2:4] == b"\x00\x00" for f in fr[:2])          # every table from row 0
    assert fr[0][4:15] == A[0].to_bytes() and len(fr[0]) == 4 + 5 * 11


def test_back_to_back_start_wins():
    c = chans(("A", 1))
    for order in (0, 1):
        seq = hwconfig.new_sequence()
        p = [(10e-6, 10e-6, 50.0), (20e-6, 10e-6, 60.0)]
        for st, du, f in (p if order == 0 else p[::-1]):
            DS.add_dds_pulse(seq, c["A"], st, du, f, 0.0)
        _, prog = DS.compile_sequence(seq, c)
        assert prog.ticks == [250, 500, 750]
        assert [(r.freq_hz, r.rf_on) for r in prog.rows["A"][1:]] == \
            [(50e6, True), (60e6, True), (60e6, False)], order


def test_manual_state_is_row0():
    c = {"A": DS.DDSChannel("A", 4, frequency_mhz=80.0, amplitude_dbm=3.0, on=True)}
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, c["A"], 10e-6, 10e-6, 50.0, 0.0)
    _, prog = DS.compile_sequence(seq, c)
    r0 = prog.rows["A"][0]
    assert (r0.freq_hz, r0.rf_on, r0.vga) == (80e6, True, c["A"].cal.code(3.0))


def test_frequency_zero_means_off_and_zero_length_ignored():
    c = chans(("A", 1))
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, c["A"], 10e-6, 10e-6, 0.0, 99.0)     # off pulse: no amp check
    DS.add_dds_pulse(seq, c["A"], 50e-6, 0.0, 50.0, 0.0)       # ignored
    _, prog = DS.compile_sequence(seq, c)
    assert prog.ticks == [250, 500]
    assert all(not r.rf_on for r in prog.rows["A"])


def test_ttl_only_sequence_has_no_dds_program():
    seq = hwconfig.new_sequence()
    seq.add_pulse('ttl_0', 1e-6, 1e-6)
    lines, prog = DS.compile_sequence(seq, hwconfig.DDS_CHANNELS)
    assert prog is None and lines == seq.to_lines()


def expect_error(fn, exc=DS.DDSError):
    try:
        fn()
    except exc:
        return
    raise AssertionError("expected " + exc.__name__)


def test_errors():
    c = chans(("A", 1), ("B", 2))

    def compiled(*pulses, channels=c):
        seq = hwconfig.new_sequence()
        for name, st, du, f in pulses:
            DS.add_dds_pulse(seq, channels[name], st, du, f, 0.0)
        return DS.compile_sequence(seq, channels)

    expect_error(lambda: compiled(("A", 10e-6, 20e-6, 50.0), ("A", 20e-6, 20e-6, 60.0)))  # overlap
    expect_error(lambda: compiled(("A", 10e-6, 3e-6, 50.0)))                  # 3 us pulse
    expect_error(lambda: compiled(("A", 10e-6, 10e-6, 50.0), ("B", 12e-6, 10e-6, 50.0)))  # 2 us apart
    expect_error(lambda: compiled(("A", 2e-6, 10e-6, 50.0)))                  # first change < 5 us
    expect_error(lambda: compiled(("A", 0.0, 10e-6, 50.0)))                   # start at t=0
    expect_error(lambda: compiled(("A", 10e-6, 10e-6, 500.0)))                # > 400 MHz
    expect_error(lambda: compiled(("A", 10e-6, 10e-6, 50.0),
                                  channels={"A": c["A"], "Z": DS.DDSChannel("Z", 1)}))  # shared addr
    expect_error(lambda: compiled(("A", 10e-6, 10e-6, 50.0),
                                  channels={"A": c["A"], "Z": DS.DDSChannel("Z", 31)}))  # bcast + other
    expect_error(lambda: DS.add_dds_pulse(hwconfig.new_sequence(), c["A"], 1e-5, 1e-5, 50.0, 20.0))  # dBm
    expect_error(lambda: DS.add_dds_pulse(hwconfig.new_sequence(), c["A"], 1e-5, 1e-5, 50.0, 0.0,
                                          ramp_rate_mhz=1.0))
    # AdvanceDDS is the compiler's
    seq = hwconfig.new_sequence()
    seq.add_pulse('AdvanceDDS', 1e-3, 1e-6)
    DS.add_dds_pulse(seq, c["A"], 10e-6, 10e-6, 50.0, 0.0)
    expect_error(lambda: DS.compile_sequence(seq, c))
    # unknown channel name
    seq = hwconfig.new_sequence()
    DS.add_dds_pulse(seq, DS.DDSChannel("Q", 5), 10e-6, 10e-6, 50.0, 0.0)
    expect_error(lambda: DS.compile_sequence(seq, c))


def test_row_limit():
    init = {"A": D.OFF}
    entries = [("A", 200 * (k + 1), D.OFF, 'start' if k % 2 == 0 else 'stop') for k in range(8191)]
    entries.append(("A", 200 * 8192, D.OFF, 'start'))
    DS.build_table(entries[:-1], init)                     # 8191 changes -> 8192 rows: fits
    expect_error(lambda: DS.build_table(entries, init))    # one more: does not


def test_bus_seconds():
    fr = DS.DDSProgram({"A": DS.DDSChannel("A", 31)}, {"A": [D.OFF] * 8192},
                       list(range(8191)), 0).frames()
    t = DS.bus_seconds(fr)
    assert 0.04 < t < 0.08, t                              # ~90 KB at 25 MHz ~ 30 ms raw


# ---------------------------------------------------------------------------
# legacy reference (servers/pulser/sequence.py parseDDS, py3 transliteration)
# ---------------------------------------------------------------------------
def legacy_parse(entries_in, state, reset_step=3):
    state = dict(state)
    pulses_end = dict.fromkeys(state, (0, 'stop'))
    prog = {n: [] for n in state}
    adv = []
    last_time = 0
    entries = sorted(entries_in, key=lambda t: t[1])
    possible_error = (0, '')
    start = None
    while True:
        try:
            name, start, num, typ = entries.pop(0)
        except IndexError:
            if start == last_time:
                for n in prog:
                    prog[n].append(state[n])
                adv.append(last_time)
            return prog, adv
        end_time, end_typ = pulses_end[name]
        if start > last_time:
            if possible_error[0] == last_time and len(possible_error[1]):
                raise Exception(possible_error[1])
            for n in prog:
                prog[n].append(state[n])
            if not last_time == 0:
                adv.append(last_time)
            last_time = start
        if start == end_time:
            if end_typ == 'stop' and typ == 'start':
                possible_error = (0, '')
                state[name] = num
                pulses_end[name] = (start, typ)
            elif end_typ == 'start' and typ == 'stop':
                possible_error = (0, '')
        elif end_typ == typ:
            possible_error = (start, 'overlap')
            state[name] = num
            pulses_end[name] = (start, typ)
        else:
            state[name] = num
            pulses_end[name] = (start, typ)


def test_matches_legacy_parseDDS_random():
    rng = random.Random(2026_11_13)
    names = ["A", "B", "C"]
    c = {n: DS.DDSChannel(n, addr=i, frequency_mhz=10.0 + i, on=bool(i % 2))
         for i, n in enumerate(names)}
    grid = 8e-6                                            # >= 5 us between any two changes
    for trial in range(300):
        seq = hwconfig.new_sequence()
        pulses = []
        for n in names:
            k = rng.randint(1, 4)
            for _ in range(rng.randint(0, 6)):
                dur = rng.randint(1, 4)
                pulses.append((n, k, dur, rng.choice([20.0, 30.0, 40.0, 0.0])))
                k += dur + rng.choice([0, 0, 1, 3])        # back-to-back is common
        if not pulses:
            continue
        rng.shuffle(pulses)                                # insertion order must not matter
        for n, k, dur, f in pulses:
            DS.add_dds_pulse(seq, c[n], k * grid, dur * grid, f, 1.0)
        _, prog = DS.compile_sequence(seq, c)
        ref_rows, ref_adv = legacy_parse(seq.dds_entries, {n: ch.manual_row() for n, ch in c.items()})
        assert prog.rows == ref_rows, trial
        assert prog.ticks == ref_adv, trial


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"test_dds_sequence: {len(tests)} tests passed")
    sys.exit(0)
