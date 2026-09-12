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
from labrad.units import WithUnit

from scan_methods import experiment

from experiment.pulser_sequences.led_blink_seq import LedBlinkSequence

# default seeded into the vault the first time, if LedBlink.on_time is absent:
# (min, max, current) in seconds -- a 'parameter' typed value
DEFAULT_ON_TIME = ('parameter', [WithUnit(0.02, 's'), WithUnit(2.0, 's'), WithUnit(0.25, 's')])
REG_PATH = ['', 'Servers', 'Parameter Vault', 'LedBlink']


class LedBlinkFromVault(experiment):

    name = 'LED Blink (from ParameterVault)'
    repeats = 4                      # how many times to replay the sequence

    @classmethod
    def all_required_parameters(cls):
        # pull the sequence's required parameters up so ScriptScanner loads them
        return LedBlinkSequence.all_required_parameters()

    def _connect(self):
        # runs before the required parameters are loaded -- make sure they exist
        # so the demo works out of the box (thereafter the vault value governs it)
        super()._connect()
        self._ensure_parameters()

    def _ensure_parameters(self):
        if self.pv is None:
            return                   # no ParameterVault; base class will report it
        try:
            self.pv.get_parameter('LedBlink', 'on_time')
            return                   # already present -- use whatever the vault holds
        except Exception:
            pass
        # seed a default straight into the registry, then reload the vault
        reg = self.cxn.registry
        reg.cd(REG_PATH, True)
        reg.set('on_time', DEFAULT_ON_TIME)
        self.pv.reload_parameters()
        print("LedBlinkFromVault: seeded LedBlink.on_time = 0.25 s (edit it in the ParameterVault)")

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
