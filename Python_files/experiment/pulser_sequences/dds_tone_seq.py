"""
dds_tone_seq.py -- the DDS example sequence: one DDS pulse whose frequency, amplitude
and length come from the ParameterVault (roadmap 4.5, ScriptScanner + addDDS).

    0 .. LEAD               the board sits on row 0 = the channel's manual state
    LEAD .. LEAD+duration   DDS_bench at DDSTone.frequency / DDSTone.amplitude, RF on
                            (+ a 'ttl_0' marker over the same window, for a scope)
    then                    RF off (frequency kept); the sequence's ResetDDS pulse
                            (TTL19 -> RAMRESET line) returns the board to row 0

Long pulses (seconds) so a frequency counter can read each run.
"""
from labrad.units import WithUnit

from experiment.pulse_sequence import pulse_sequence


class DdsToneSequence(pulse_sequence):

    required_parameters = [
        ('DDSTone', 'frequency'),       # MHz
        ('DDSTone', 'amplitude'),       # dBm
        ('DDSTone', 'duration'),        # s
    ]

    channel = 'DDS_bench'               # pulser3.hwconfig.DDS_CHANNELS
    LEAD = WithUnit(0.5, 's')           # row 0 (manual state) before the pulse

    def sequence(self):
        p = self.parameters.DDSTone
        t0 = self.start + self.LEAD
        self.addDDS(self.channel, t0, p.duration, p.frequency, p.amplitude)
        self.addTTL('ttl_0', t0, p.duration)
