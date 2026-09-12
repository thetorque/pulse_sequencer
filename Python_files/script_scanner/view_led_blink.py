"""
view_led_blink.py -- preview the LED Blink pulse sequence in seq_viewer.

Open this file from seq_viewer / seq_editor (Open...): it defines build_sequence()
returning a pulser3.Sequence built from the SAME sequence the led_blink experiment
runs (pulse_sequences.alternating_blink). No hardware, no LabRAD -- it just turns
the (channel, start, duration) pulse list into a Sequence the viewer can draw.

This is the payoff of keeping the sequence in pulse_sequences.py: the exact
pattern an experiment will run can be previewed on any laptop.
"""
import os
import sys

# make pulser3 (parent dir) and pulse_sequences (this dir) importable whether this
# file is opened by the viewer or imported directly
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pulser3 import hwconfig                    # noqa: E402
from pulse_sequences import alternating_blink   # noqa: E402


def _led_channels(max_leds=8):
    # the switchable LED outputs (number < 12), sorted by number -- same set the
    # led_blink experiment picks from the Pulser's Get Channels
    chans = sorted((num, name) for name, num in hwconfig.CHANNELS.items() if num < 12)
    return [name for num, name in chans][:max_leds]


def build_sequence():
    channels = _led_channels()
    pulses, total_time = alternating_blink(channels, on_time=0.25, cycles=3)
    seq = hwconfig.new_sequence()
    for channel, start_s, duration_s in pulses:
        seq.add_pulse(channel, start_s, duration_s)
    seq.extend_length(total_time)
    return seq
