"""
sample_experiment.py -- hardware-free example experiments for ScriptScanner.

These exist so the whole orchestrator (queue / schedule / progress / pause /
stop / scan-into-DataVault) can be exercised on any laptop, before the real
experiment layer (Pulser / PMT / camera scripts) is ported. Each is a normal
`scan_methods.experiment` subclass:

  - sleep_experiment : a param-free run that steps through a short sleep,
        reporting progress and checking pause/stop every step. Runnable with only
        the manager + ScriptScanner. Its run() returns a noisy reading so
        `New Script Repeat` (save_data) produces a Data Vault dataset.

  - pmt_point : a synthetic "measurement" that returns a Gaussian line shape in a
        scanned parameter (default ('Spectrum','frequency')) plus noise. Point it
        at `New Script Scan` and you get a lineshape dataset in the Data Vault
        that the live grapher plots -- no detector, no Pulser needed.

  - crashing_example : raises in initialize, to verify the error-finish path.

Real experiment scripts (that talk to the Pulser, PMT, camera, DAC) look the
same but do hardware work in initialize/run/finalize; add them to
configuration.py as you port the experiment layer.
"""
import math
import random
import time

from scan_methods import experiment


def _magnitude(value, default=0.0):
    """Best-effort convert a scanned value (number or labrad Value) to a float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        # a dimensioned labrad Value: read it back in its own units
        try:
            return float(value[value.units])
        except Exception:
            return default


class sleep_experiment(experiment):

    name = 'Sleep Experiment'
    required_parameters = []          # no ParameterVault needed

    # defaults (a real experiment would load these from the ParameterVault)
    steps = 20
    step_duration = 0.25              # seconds per step

    def initialize(self, cxn, context, ident):
        # store what we need to report progress / honour pause+stop from run()
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']

    def run(self, cxn, context):
        for i in range(self.steps):
            if self.pause_or_stop():   # blocks while paused; True if we should stop
                return None
            time.sleep(self.step_duration)
            # report within this run's slice so scan/repeat progress stays smooth
            self.set_progress((i + 1) / self.steps)
        # a noisy reading, so repeat/scan wrappers have something to save
        return 100.0 + random.gauss(0.0, 5.0)

    def finalize(self, cxn, context):
        pass


class pmt_point(experiment):

    name = 'PMT Point'
    required_parameters = []          # the scanned parameter is injected by the scan wrapper

    # which parameter the scan sweeps, and a synthetic line shape over it
    scan_parameter = ('Spectrum', 'frequency')
    line_center = 0.0
    line_width = 1.0
    line_height = 1000.0
    background = 20.0

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']

    def run(self, cxn, context):
        if self.pause_or_stop():
            return None
        key = '{0}.{1}'.format(*self.scan_parameter)
        x = _magnitude(self.parameters.get(key, self.line_center))
        # Gaussian peak + shot-like noise -- a stand-in for a real PMT reading
        arg = (x - self.line_center) / self.line_width
        counts = self.background + self.line_height * math.exp(-0.5 * arg * arg)
        counts += random.gauss(0.0, math.sqrt(max(counts, 1.0)))
        time.sleep(0.05)              # pretend a measurement takes a moment
        return counts

    def finalize(self, cxn, context):
        pass


class crashing_example(experiment):

    name = 'crashing_example'
    required_parameters = []

    def initialize(self, cxn, context, ident):
        raise Exception("In a case of a crash, the real message would follow")
