"""
led_blink_experiment.py -- a ScriptScanner experiment that runs a pulse sequence
whose parameters come from the ParameterVault.

This is the full experiment-layer pattern, end to end:

    ParameterVault  --(ScriptScanner loads required_parameters)-->  self.parameters
        -->  LedBlinkSequence(self.parameters)  -->  programSequence(pulser)  -->  run

`all_required_parameters` is delegated to the sequence, so ScriptScanner loads
exactly what the sequence needs (here LedBlink.on_time) into `self.parameters`
before `run`. Seed that parameter first (see experiment/seed_parameters.py or the
ParameterVault). Needs the manager + Pulser + ParameterVault.
"""
from scan_methods import experiment

from experiment.pulser_sequences.led_blink_seq import LedBlinkSequence


class LedBlinkFromVault(experiment):

    name = 'LED Blink (from ParameterVault)'
    repeats = 4                      # how many times to replay the sequence

    @classmethod
    def all_required_parameters(cls):
        # pull the sequence's required parameters up so ScriptScanner loads them
        return LedBlinkSequence.all_required_parameters()

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']
        self.pulser = cxn.pulser

    def run(self, cxn, context):
        # build the sequence from the parameters loaded from the ParameterVault,
        # then program it onto the Pulser
        seq = LedBlinkSequence(self.parameters)
        seq.programSequence(self.pulser)
        total = float(seq.end['s'])
        for r in range(self.repeats):
            if self.pause_or_stop():
                self.pulser.stop_sequence()
                return None
            self.pulser.start_single()
            self.pulser.wait_sequence_done(total + 1.0)
            self.set_progress((r + 1) / self.repeats)
        return None

    def finalize(self, cxn, context):
        pass
