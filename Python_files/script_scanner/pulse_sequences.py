"""
pulse_sequences.py -- reusable pulse-sequence definitions, kept SEPARATE from the
experiment logic.

This is the pattern the real lab uses (its legacy `experiment/pulser_sequences/`):
a sequence -- "what pulses happen, and when" -- is defined once here, and an
experiment script *imports* it rather than building it inline. That keeps complex
sequences in one place, lets several experiments share them, and lets you preview
or tweak a sequence without touching the experiment that runs it.

Each builder here returns `(pulses, total_time)`, where `pulses` is a list of
`(channel_name, start_s, duration_s)` tuples -- exactly what an experiment feeds
to the Pulser's `add_ttl_pulse`. Nothing here talks to hardware; it just describes
timing, so a builder can be unit-tested or plotted on its own.
"""


def alternating_blink(channels, on_time=0.25, cycles=3):
    """A two-bank blinker: alternately flash the even- and odd-indexed channels.

    even channels ON for on_time, then odd channels ON for on_time -- repeated
    `cycles` times. Returns (pulses, total_time).
    """
    even = channels[0::2]
    odd = channels[1::2]
    pulses = []
    t = 0.0
    for _ in range(cycles):
        for ch in even:
            pulses.append((ch, t, on_time))
        t += on_time
        for ch in odd:
            pulses.append((ch, t, on_time))
        t += on_time
    return pulses, t


def blink_together(channels, on_time=0.2, off_time=0.2, blinks=4):
    """Flash all the given channels together `blinks` times. Returns (pulses, total_time)."""
    pulses = []
    t = 0.0
    for _ in range(blinks):
        for ch in channels:
            pulses.append((ch, t, on_time))
        t += on_time + off_time
    return pulses, t
