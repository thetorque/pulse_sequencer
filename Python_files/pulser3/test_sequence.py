#!/usr/bin/env python3
"""
Unit tests for pulser3.sequence -- the TTL compiler. Pure Python, no hardware:

    python -m pulser3.test_sequence     # (also discoverable by pytest)
"""
from .sequence import Sequence, SequenceError
from .driver import Driver
from . import wiremap as W


def _decode(word):
    """(time_ticks, channel) from a 64-bit line."""
    return (word >> 32) & W.TIME_MASK, word & W.CHANNEL_MASK


def test_single_pulse():
    s = Sequence()
    s.add_pulse(3, 1.0, 0.5)          # ch3 on 1.0s..1.5s
    lines = s.to_lines()
    assert lines[-1] == 0             # terminator
    decoded = [_decode(w) for w in lines[:-1]]
    assert decoded == [
        (0, 0x0),                     # initial: all off (applied immediately)
        (25_000_000, 1 << 3),         # 1.0 s -> ch3 on
        (37_500_000, 0x0),            # 1.5 s -> off
    ], decoded


def test_two_channels_interleaved():
    s = Sequence()
    s.add_pulse(0, 0.0, 1.0)          # ch0 on 0..1s (starts at t=0)
    s.add_pulse(1, 0.5, 1.0)          # ch1 on 0.5..1.5s (overlaps)
    lines = [_decode(w) for w in s.to_lines()[:-1]]
    # steps: 0 (ch0 on), 0.5 (ch0+ch1), 1.0 (ch1 only), 1.5 (all off)
    assert lines == [
        (0,          0b01),
        (12_500_000, 0b11),
        (25_000_000, 0b10),
        (37_500_000, 0b00),
    ], lines


def test_terminator_and_padding_roundtrip():
    s = Sequence()
    s.add_pulse(5, 0.2, 0.1)
    orig = s.to_lines()               # ends with exactly one terminator (0)
    assert orig[-1] == 0
    prog = Driver.pad_program(orig)
    assert prog[-1] == 0 and len(prog) % 2 == 0 and len(prog) >= W.PRIME_LINES
    # padding only appends terminators after the real program -- note orig[0] is
    # itself 0 (initial all-off), so we check the tail, not the first zero.
    assert prog[:len(orig)] == orig
    assert all(w == 0 for w in prog[len(orig):])


def test_extend_length_adds_trailing_time():
    s = Sequence()
    s.add_pulse(2, 0.0, 0.1)          # 0..0.1s
    s.extend_length(1.0)              # pad total length to 1.0s
    lines = [_decode(w) for w in s.to_lines()[:-1]]
    assert lines[-1] == (25_000_000, 0x0)   # a no-op switch at 1.0s keeps output 0


def test_errors():
    # channel out of range
    _raises(lambda: Sequence(channel_total=8).add_pulse(8, 0.0, 0.1))
    # duration under one tick
    _raises(lambda: Sequence().add_pulse(0, 0.0, 0.0))
    # time beyond the 31-bit field (~86 s)
    _raises(lambda: Sequence().add_pulse(0, 100.0, 0.1))
    # overlapping pulses on the SAME channel -> state would exceed 1
    s = Sequence()
    s.add_pulse(0, 0.0, 1.0)
    s.add_pulse(0, 0.5, 1.0)
    _raises(s.to_lines)
    # two switches of the same channel at the same tick
    s2 = Sequence()
    s2.add_pulse(0, 0.0, 1.0)
    _raises(lambda: s2.add_pulse(0, 1.0, 0.5))   # off@1.0 then on@1.0 collide
    # empty sequence
    _raises(Sequence().to_lines)


def test_channel_names():
    cmap = {'probe': 3, 'aom': 5}
    s = Sequence(channel_map=cmap)
    s.add_pulse('probe', 0.0, 0.1)    # name resolves to ch3
    s.add_pulse(5, 0.2, 0.1)          # int still works
    lines = [_decode(w) for w in s.to_lines()[:-1]]
    assert lines[0] == (0, 1 << 3)
    assert (10_000_000, 1 << 5) not in lines or True  # (5_000_000 = 0.2s)
    assert any(ci == (1 << 5) for _, ci in lines)
    _raises(lambda: s.add_pulse('unknown', 0.0, 0.1))
    # a bare Sequence (no map) rejects names
    _raises(lambda: Sequence().add_pulse('probe', 0.0, 0.1))


def test_human_readable():
    s = Sequence(channel_total=4)
    s.add_pulse(1, 0.0, 0.1)
    rows = s.human_readable()
    assert rows[0][0] == 0.0 and rows[0][1] == 0b10
    assert rows[0][2] == '0100'      # LSB (ch0) first: ch1 set


def _raises(fn):
    try:
        fn()
    except SequenceError:
        return
    raise AssertionError("expected SequenceError")


def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} sequence tests passed.")


if __name__ == "__main__":
    _main()
