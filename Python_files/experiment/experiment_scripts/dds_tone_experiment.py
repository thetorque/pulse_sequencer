"""
dds_tone_experiment.py -- a ScriptScanner experiment that plays a DDS pulse whose
parameters come from the ParameterVault (roadmap 4.5: ScriptScanner end to end with
addDDS).

    ParameterVault DDSTone.{frequency, amplitude, duration}
        --> DdsToneSequence (addDDS on 'DDS_bench' + a ttl_0 marker)
        --> programSequence(pulser)  (Pulser 'Add DDS Pulses' -> DDS backplane bus)
        --> start_single, wait

Run it single / repeat, or scan DDSTone.frequency (MHz) or DDSTone.amplitude (dBm)
from the ScriptScanner GUI: every point re-programs the board's table, plays the
pulse once, and returns the programmed frequency in MHz, so a scan writes a
frequency staircase into the Data Vault that should match a frequency counter.

The parameters are seeded the first time (see DEFAULTS); thereafter the vault
values govern. Needs the manager + Pulser + ParameterVault (+ Data Vault to scan).
"""
from labrad.units import WithUnit

from scan_methods import experiment

from experiment.pulser_sequences.dds_tone_seq import DdsToneSequence

REG_PATH = ['', 'Servers', 'Parameter Vault', 'DDSTone']
# 'parameter' typed values: (min, max, current)
DEFAULTS = {
    'frequency': ('parameter', [WithUnit(10.0, 'MHz'), WithUnit(400.0, 'MHz'), WithUnit(90.0, 'MHz')]),
    'amplitude': ('parameter', [WithUnit(-40.0, 'dBm'), WithUnit(0.0, 'dBm'), WithUnit(-10.0, 'dBm')]),
    'duration': ('parameter', [WithUnit(0.001, 's'), WithUnit(30.0, 's'), WithUnit(4.0, 's')]),
}


class DdsToneFromVault(experiment):

    name = 'DDS Tone (from ParameterVault)'

    @classmethod
    def all_required_parameters(cls):
        return DdsToneSequence.all_required_parameters()

    def _connect(self):
        # runs before the required parameters are loaded -- make sure they exist
        super()._connect()
        self._ensure_parameters()

    def _ensure_parameters(self):
        if self.pv is None:
            return                   # no ParameterVault; the base class reports it
        missing = []
        for name in DEFAULTS:
            try:
                self.pv.get_parameter('DDSTone', name)
            except Exception:
                missing.append(name)
        if not missing:
            return
        reg = self.cxn.registry
        reg.cd(REG_PATH, True)
        for name in missing:
            reg.set(name, DEFAULTS[name])
        self.pv.reload_parameters()
        print("DdsToneFromVault: seeded DDSTone." + ", DDSTone.".join(missing))

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']
        self.pulser = cxn.pulser

    def run(self, cxn, context):
        if self.pause_or_stop():
            return None
        seq = DdsToneSequence(self.parameters)
        seq.programSequence(self.pulser)
        self.pulser.start_single()
        self.pulser.wait_sequence_done(float(seq.end['s']) + 2.0)
        self.set_progress(1.0)
        return float(self.parameters.DDSTone.frequency['MHz'])

    def finalize(self, cxn, context):
        pass
