# experiment -- the experiment layer (py3)

The physics on top of the servers: **pulse sequences** and the **experiment
scripts** that run them. This is the py3 port of the lab's legacy
`experiment/` tree, built on the ported ScriptScanner + Pulser + ParameterVault.

```
ParameterVault  --(ScriptScanner loads required_parameters)-->  experiment.parameters
     -->  a pulse_sequence(parameters)  -->  programSequence(pulser)  -->  run
```

## Layout

| path | role |
|---|---|
| `pulse_sequence.py` | base class for composable pulse sequences (addTTL/addDDS, subsequences, `programSequence`) |
| `pulser_sequences/` | concrete sequences (the "what pulses, when"), e.g. `led_blink_seq.py` |
| `experiment_scripts/` | ScriptScanner experiments that load parameters and run a sequence, e.g. `led_blink_experiment.py` |
| `seed_parameters.py` | seed the ParameterVault with the parameters the examples need |

This mirrors the legacy split: a **sequence** describes timing and declares its
`required_parameters`; an **experiment** pulls those parameters from the
ParameterVault, builds the sequence, programs it, and runs it (with progress /
pause / stop).

## Writing a sequence

Subclass `pulse_sequence`, declare `required_parameters`, and lay out pulses in
`sequence()` using real units:

```python
from labrad.units import WithUnit
from experiment.pulse_sequence import pulse_sequence

class MySequence(pulse_sequence):
    required_parameters = [('MyGroup', 'pulse_time')]

    def sequence(self):
        t = self.parameters.MyGroup.pulse_time          # from the ParameterVault
        self.addTTL('BIG_MOT_SH', WithUnit(0, 's'), t)  # channel, start, duration
```

`programSequence(pulser)` sends the TTL pulses to the Pulser. Sequences can be
**composed**: list other sequences in `required_subsequences` and insert them with
`addSequence(...)`; `all_required_parameters()` then gathers everything the whole
tree needs.

**DDS pulses:** `addDDS(channel, start, duration, frequency, amplitude[, phase,
ramp_rate, amp_ramp_rate])` with a channel from `pulser3.hwconfig.DDS_CHANNELS`
(bench: `DDS_bench`). `programSequence` sends them with Pulser 'Add DDS Pulses';
the Pulser compiles the row tables, loads them over the DDS backplane bus and adds
the AdvanceDDS / ResetDDS (TTL 18/19) pulses. Rules: changes on DDS channels >= 5 us
apart, no ramps, frequency 0 = off. Example: `pulser_sequences/dds_tone_seq.py` +
`experiment_scripts/dds_tone_experiment.py` ("DDS Tone (from ParameterVault)").

## Writing an experiment

Subclass `scan_methods.experiment`, delegate `all_required_parameters` to the
sequence, and run it:

```python
from scan_methods import experiment
from experiment.pulser_sequences.my_seq import MySequence

class MyExperiment(experiment):
    name = 'My Experiment'

    @classmethod
    def all_required_parameters(cls):
        return MySequence.all_required_parameters()

    def initialize(self, cxn, context, ident):
        self.ident = ident
        self.sc = cxn.servers['ScriptScanner']
        self.pulser = cxn.pulser

    def run(self, cxn, context):
        seq = MySequence(self.parameters)     # parameters were loaded from the vault
        seq.programSequence(self.pulser)
        self.pulser.start_single()
        self.pulser.wait_sequence_done(float(seq.end['s']) + 1.0)
        return None
```

Register it in `script_scanner/configuration.py` by dotted path -- e.g.
`('experiment.experiment_scripts.my_exp', 'MyExperiment')`. The ScriptScanner
server puts `Python_files` on `sys.path`, so `experiment.*` imports resolve.

## The bundled example: LED Blink (from ParameterVault)

- `pulser_sequences/led_blink_seq.py` -- `LedBlinkSequence`: a two-bank LED
  blinker; the ON time is a required parameter (`LedBlink.on_time`).
- `experiment_scripts/led_blink_experiment.py` -- `LedBlinkFromVault`: loads that
  parameter, builds the sequence, and replays it a few times with progress.

### Run it

1. Start the manager, Pulser, ParameterVault, and ScriptScanner (via the Launcher).
2. In the Script Scanner GUI, pick **LED Blink (from ParameterVault)** and **Run once**.

The LEDs blink in two alternating banks. The ON time is whatever
`LedBlink.on_time` holds in the vault; **the experiment seeds a default
(0.25 s) the first time if it's missing**, so it works out of the box. Change the
speed by editing `LedBlink.on_time` -- most easily in the **Parameter Editor**
(`pulser_gui/parameter_editor.py`, or the Parameters tab of the Workbench) -- then
run again. That's the ParameterVault-driven pattern.

## The DDS example: DDS Tone (from ParameterVault)

- `pulser_sequences/dds_tone_seq.py` -- `DdsToneSequence`: 0.5 s on the channel's
  manual state, then one DDS pulse on `DDS_bench` at `DDSTone.frequency` (MHz) /
  `DDSTone.amplitude` (dBm) for `DDSTone.duration` (s), with a `ttl_0` marker over
  the pulse; the ResetDDS pulse at the end returns the board to row 0.
- `experiment_scripts/dds_tone_experiment.py` -- `DdsToneFromVault`: seeds the
  three parameters the first time (90 MHz, -10 dBm, 4 s), plays the pulse once per
  run and returns the programmed frequency (MHz), so **scanning
  `DDSTone.frequency`** writes a frequency staircase into the Data Vault that a
  frequency counter on the DDS output should match point by point.

## Status / next

- Framework + one worked TTL example: **done**.
- The real physics scripts (`MOT_loading`, `Clock_spectrum`, …) also need the
  hardware servers that aren't ported yet -- the NI analog/DAC server, the Andor
  camera, and DDS -- so they'll land as those come online. The legacy versions
  live under `old_legacy_code/experiment/` for reference.
- A dedicated ParameterVault editor GUI would let scans pick a parameter instead
  of typing it.
