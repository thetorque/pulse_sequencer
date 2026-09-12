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

from labrad.units import s

from scan_methods import experiment
from pulse_sequences import alternating_blink   # sequence defined in its own module


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


class led_staircase(experiment):
    """Light the switchable TTL outputs (the LEDs) in a rising staircase.

    A real pulse-sequence experiment: it drives the Pulser. Each LED turns on one
    step later than the previous and stays on, so the bar fills up like a
    staircase, holds at the top, then all turn off -- looped a few times for a
    visible animation. Needs the Pulser server (and its FPGA/board).

    It uses whatever channels are wired to numbers 0..11 (the override outputs the
    switch panel controls), sorted by number, up to `max_leds`.
    """

    name = 'LED Staircase'
    required_parameters = []

    step_duration = 0.3       # s between successive LEDs turning on
    hold = 0.6                # s all LEDs stay lit at the top
    cycles = 5                # how many times to run the staircase
    max_leds = 8              # cap on how many LEDs to use

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']
        self.pulser = cxn.pulser
        # the switchable override outputs (number < 12) are the LEDs; sort by number
        chans = sorted((num, name) for (name, num) in self.pulser.get_channels() if num < 12)
        self.channels = [name for (num, name) in chans][:self.max_leds]
        if not self.channels:
            raise Exception("No switchable TTL channels (number < 12) found for the LEDs")
        self._program_staircase()

    def _program_staircase(self):
        p = self.pulser
        n = len(self.channels)
        # LED i turns on at i*step and stays on until the end -> a rising staircase
        self.total_time = n * self.step_duration + self.hold
        p.new_sequence()
        for i, ch in enumerate(self.channels):
            start = i * self.step_duration
            duration = self.total_time - start
            p.add_ttl_pulse(ch, start * s, duration * s)
        p.extend_sequence_length(self.total_time * s)
        p.program_sequence()

    def run(self, cxn, context):
        p = self.pulser
        for cycle in range(self.cycles):
            if self.pause_or_stop():      # blocks while paused; True if we should stop
                p.stop_sequence()
                return None
            p.start_single()              # replay the programmed staircase
            p.wait_sequence_done(self.total_time + 1.0)
            self.set_progress((cycle + 1) / self.cycles)
        return None

    def finalize(self, cxn, context):
        pass


class led_blink(experiment):
    """Blink the LEDs using a sequence defined in a SEPARATE module.

    Same idea as led_staircase (drives the Pulser), but the pulse pattern is not
    built here -- it's imported from pulse_sequences.py. This is how you build up
    more complex experiments: keep the sequence ("what pulses, when") in its own
    file and just import + program it in the experiment. Needs the Pulser server.
    """

    name = 'LED Blink'
    required_parameters = []

    on_time = 0.25            # s each bank stays lit
    blink_cycles = 3          # even/odd alternations per run of the sequence
    repeats = 4               # how many times to replay the sequence
    max_leds = 8              # cap on how many LEDs to use

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']
        self.pulser = cxn.pulser
        chans = sorted((num, name) for (name, num) in self.pulser.get_channels() if num < 12)
        self.channels = [name for (num, name) in chans][:self.max_leds]
        if not self.channels:
            raise Exception("No switchable TTL channels (number < 12) found for the LEDs")
        # the sequence lives in pulse_sequences.py -- we just import + program it
        self.pulses, self.total_time = alternating_blink(self.channels,
                                                         on_time=self.on_time,
                                                         cycles=self.blink_cycles)
        self._program()

    def _program(self):
        p = self.pulser
        p.new_sequence()
        for ch, start, duration in self.pulses:
            p.add_ttl_pulse(ch, start * s, duration * s)
        p.extend_sequence_length(self.total_time * s)
        p.program_sequence()

    def run(self, cxn, context):
        p = self.pulser
        for r in range(self.repeats):
            if self.pause_or_stop():
                p.stop_sequence()
                return None
            p.start_single()
            p.wait_sequence_done(self.total_time + 1.0)
            self.set_progress((r + 1) / self.repeats)
        return None

    def finalize(self, cxn, context):
        pass


class crashing_example(experiment):

    name = 'crashing_example'
    required_parameters = []

    def initialize(self, cxn, context, ident):
        raise Exception("In a case of a crash, the real message would follow")
