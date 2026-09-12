# ScriptScanner -- experiment orchestrator (py3)

The piece that **runs experiments**. It discovers experiment classes, exposes
them over LabRAD, and **queues / schedules / scans** them through a priority
scheduler that runs each one in a worker thread while reporting progress and
honouring **pause / stop**. py3 port of the lab's legacy
`servers/script_scanner`; LabRAD name, setting IDs (0-36) and signal IDs are
unchanged, so the (later) PyQt5 GUI and any listener see the same interface.

```
python script_scanner/script_scanner.py     # needs the manager running
```

## Files

| file | role |
|---|---|
| `script_scanner.py` | the LabRAD server (settings 0-36) |
| `scheduler.py` | priority queue + running/scheduled scans; launches each in a thread |
| `script_status.py` | per-script status / progress / pause-lock (`script_semaphore`) |
| `scan_methods.py` | `experiment` base class + `single` / `repeat_reload` / `scan_experiment_1D` / `scan_experiment_1D_measure` |
| `signals.py` | LabRAD signals (queued / running / scheduled changes) |
| `configuration.py` | which experiment classes are offered + concurrency rules |
| `treedict.py` | tiny py3 stand-in for the py2 `treedict` (dotted parameter dict) |
| `sample_experiment.py` | example experiments (see below) |
| `pulse_sequences.py` | reusable pulse-sequence builders imported by experiments |
| `test_client.py` | smoke test |

## What an experiment is

Subclass `scan_methods.experiment` and implement `initialize` / `run` /
`finalize`. Declare `required_parameters` (a list of `(collection, name)`) and
they are loaded from the **ParameterVault** into `self.parameters` (a `TreeDict`,
so `self.parameters.Collection.name` or `self.parameters['Collection.name']`).
Inside a long `run`, call `self.pause_or_stop()` regularly -- it blocks while the
script is paused and returns `True` when it should stop -- and
`self.set_progress(fraction)` (0..1) to move the progress bar -- it maps into
this run's slice, so scan/repeat progress stays smooth.

Register a class by adding `(import_path, class_name)` to
`configuration.scripts`.

## The bundled examples (no hardware)

So the orchestrator is testable on any laptop, before the real experiment layer
(Pulser / PMT / camera scripts) is ported:

- **Sleep Experiment** -- param-free; steps through a short sleep, reporting
  progress and checking pause/stop each step. Runs with only the manager +
  ScriptScanner. Returns a noisy reading so `New Script Repeat` produces data.
- **PMT Point** -- a synthetic "measurement" returning a Gaussian line shape in a
  scanned parameter (default `('Spectrum','frequency')`) plus noise. Point
  `New Script Scan` at it and you get a **lineshape dataset in the Data Vault**
  that the live grapher plots -- no detector, no Pulser needed.
- **crashing_example** -- raises in `initialize`, to exercise the error path.

And two that **do** drive hardware, as real pulse-sequence examples:

- **LED Staircase** -- programs the Pulser so the switchable TTL outputs (the
  LEDs, channels 0..11) light in a rising staircase: each LED turns on one step
  later and stays on, holds at the top, then all turn off -- looped a few times.
  Shows how an experiment builds a sequence *inline* (`new_sequence` /
  `add_ttl_pulse` / `program_sequence` / `start_single` / `wait_sequence_done`)
  and stays interruptible. Needs the Pulser server + its board.
- **LED Blink** -- same idea, but the pulse pattern is **imported** from a
  separate module (`from pulse_sequences import alternating_blink`) instead of
  built inline. This is the pattern for complex experiments: keep the sequence in
  `pulse_sequences.py` (shared, testable, plottable on its own) and just program
  it in the experiment. Needs the Pulser server + its board.

`pulse_sequences.py` holds the reusable sequence builders (each returns a list of
`(channel, start_s, duration_s)` pulses); it's the py3 stand-in for the lab's
legacy `experiment/pulser_sequences/`.

### Previewing a sequence (no hardware)

`view_led_blink.py` turns the `alternating_blink` sequence into a
`pulser3.Sequence` so you can **see** it before running: start the viewer and
open that file --

```
python ../seq_viewer/seq_viewer.py     # then Open... -> script_scanner/view_led_blink.py
```

It's a tiny `build_sequence()` wrapper (import a builder from `pulse_sequences.py`,
turn its pulse tuples into a Sequence, return it). Copy the pattern to preview any
other sequence.

## Test

Start the manager + ScriptScanner (and the Data Vault for the scan step), then:

```
python script_scanner/test_client.py
```

It lists the scripts, runs a Sleep Experiment to completion (printing progress),
stops another mid-run, and -- if the Data Vault is up -- scans PMT Point over a
frequency, leaving a lineshape under `['','ScriptScanner', <date>]`.

## Ways to launch (server settings)

- **New Experiment** (`new_experiment`) -- run once (`single`).
- **New Script Repeat** (`new_script_repeat`) -- run N times, reloading
  parameters each time; optionally save each result.
- **New Script Scan** (`new_script_scan`) -- sweep one `(collection, parameter)`
  from min to max in N steps (units string), saving result vs value. Pass the
  same script for scan and measure to sweep-and-measure one experiment, or two
  different scripts to scan one while measuring another.
- **New Script Schedule** (`new_script_schedule`) -- re-queue the script every
  *duration* seconds. **Pause Script** / **Stop Script** / **Get Progress** act
  on a running id.

## Notes / py3 changes

- `treedict` (py2, C-extension, never ported) replaced by the small local
  `treedict.py` (dotted get/set + attribute access + recursive `update`).
- `print`-functions; `.iteritems()`/`.itervalues()` -> `.items()`/`.values()`;
  `.keys()` views wrapped in `list()` where a LabRAD list is returned.
- **ParameterVault is now optional** -- an experiment with no required parameters
  runs without it, so the stack is testable incrementally.
- The Pause-Or-Stop setting yields on the pause lock, but a setting can't be
  decorated with `@inlineCallbacks` directly (it hides the declared parameters
  from `@setting`, raising "Setting parameter script_ID not accepted"), so it
  delegates to an `@inlineCallbacks` helper and returns its Deferred -- the same
  pattern the other servers use for async settings.
- `scheduler.stop_running()` added -- the legacy `stopServer` called it but the
  method was missing (the resulting `AttributeError` was silently swallowed).
- `class ScriptScanner(Signals)` -- the legacy `(LabradServer, Signals)` is an
  illegal MRO in py3 (`Signals` already subclasses `LabradServer`, so a base
  can't precede its own subclass); inheriting from `Signals` alone brings in
  both.

## GUI

`../pulser_gui/script_scanner_gui.py` is the PyQt5 operator view: pick an
experiment and launch it (run once / repeat / scan / schedule), and watch the
live queue, running scripts (progress bar + pause/resume/stop), and scheduled
scans. It's also a dashboard panel. See `../pulser_gui/README.md`.

## Next

- A ParameterVault editor (the tree_view from the old GUI) so scans can pick a
  parameter instead of typing collection/name/units.
- Reuse `seq_viewer`'s `SequencePlot` to preview an experiment's pulses once the
  experiment layer exposes its sequence.
- Port the **experiment layer** (`experiment_scripts` + `pulser_sequences`) so
  the real MOT / clock experiments run here.
