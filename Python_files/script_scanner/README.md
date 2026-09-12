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
| `sample_experiment.py` | hardware-free example experiments (see below) |
| `test_client.py` | smoke test |

## What an experiment is

Subclass `scan_methods.experiment` and implement `initialize` / `run` /
`finalize`. Declare `required_parameters` (a list of `(collection, name)`) and
they are loaded from the **ParameterVault** into `self.parameters` (a `TreeDict`,
so `self.parameters.Collection.name` or `self.parameters['Collection.name']`).
Inside a long `run`, call `self.pause_or_stop()` regularly -- it blocks while the
script is paused and returns `True` when it should stop -- and
`self.sc.script_set_progress(self.ident, pct)` to move the progress bar.

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
- The Pause-Or-Stop setting is explicitly `@inlineCallbacks` (it yields on the
  pause lock; the legacy relied on implicit generator handling).
- `scheduler.stop_running()` added -- the legacy `stopServer` called it but the
  method was missing (the resulting `AttributeError` was silently swallowed).

## Next

- **script_scanner_gui** (PyQt5) -- the operator view: available experiments,
  the queue, running scripts with progress bars + pause/stop, scheduled scans.
  It will reuse `seq_viewer`'s `SequencePlot` to preview an experiment's pulses.
- Port the **experiment layer** (`experiment_scripts` + `pulser_sequences`) so
  the real MOT / clock experiments run here.
