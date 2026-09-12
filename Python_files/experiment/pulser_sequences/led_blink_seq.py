"""
led_blink_seq.py -- an example pulse sequence built on the framework.

A two-bank LED blinker whose ON time comes from the ParameterVault. It blinks the
even- and odd-indexed LED channels alternately, `cycles` times. This shows the
real pattern: the sequence declares a required parameter, reads it from
`self.parameters` (filled from the vault), and lays out TTL pulses in real units.

Channels are the switchable LED outputs (numbers 0..11 in pulser3.hwconfig).
"""
from labrad.units import WithUnit

from experiment.pulse_sequence import pulse_sequence


class LedBlinkSequence(pulse_sequence):

    required_parameters = [
        ('LedBlink', 'on_time'),        # a 'parameter' (seconds) in the ParameterVault
    ]

    even = ['ttl_0', 'sMOT_PROBE_SPIN', 'sMOT_AO', '405_ECDL']
    odd = ['sMOT_PROBE', 'BIG_MOT_SH', 'BIG_MOT_AO', '405_Raman']
    cycles = 3

    def sequence(self):
        on = self.parameters.LedBlink.on_time      # WithUnit seconds, from the vault
        t = WithUnit(0.0, 's')
        for _ in range(self.cycles):
            for ch in self.even:
                self.addTTL(ch, t, on)
            t = t + on
            for ch in self.odd:
                self.addTTL(ch, t, on)
            t = t + on
