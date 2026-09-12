# seq_viewer -- pulse-sequence timing viewer + editor

*See* a pulse sequence before you run it, or *build* one and watch it update
live. Each TTL channel is a lane whose waveform steps high when the channel is
on, across a shared time axis — a logic-analyzer view of a `pulser3.Sequence`.

| file | role |
|---|---|
| `seq_viewer.py` | read-only viewer (Demo / Open a `.py`) |
| `seq_editor.py` | interactive editor: pulse table, live diagram, Export, Program+Run |
| `seq_plot.py` | the shared `SequencePlot` timing-diagram widget |

**No hardware, no LabRAD, no manager.** It only *compiles and reads* a Sequence
(pulser3 imports fine without the `ok` module), so you can preview a sequence on
any laptop.

```
python seq_viewer/seq_viewer.py      # needs: pip install PyQt5 pyqtgraph
```

## Use

- **Demo** — a small built-in sequence, for an instant look.
- **Open…** — a `.py` file that defines `build_sequence()` returning a
  `pulser3.Sequence` (or a module-level `sequence`). For example:

  ```python
  from pulser3 import Sequence, hwconfig

  def build_sequence():
      seq = Sequence(channel_map=hwconfig.CHANNELS)
      seq.add_pulse('sMOT_PROBE', 0.1, 0.5)   # channel, start_s, duration_s
      seq.add_pulse('BIG_MOT_SH', 0.3, 0.5)
      seq.extend_length(1.0)
      return seq
  ```

- **Show all channels** — toggle between only the channels used in the sequence
  (default) and all 32.
- Drag to pan, scroll to zoom **the time axis** (channels stay put). The x-axis
  auto-labels in s / ms / µs.

## How it works

It calls `Sequence.human_readable()` (the per-switching-time state), builds a
digital step waveform per channel, and plots them as stacked lanes with pyqtgraph.
Channel names come from `pulser3.hwconfig.CHANNELS`.

## Editor (`seq_editor.py`)

```
python seq_viewer/seq_editor.py
```

- A **pulse table** — each row is `channel` (dropdown) / `start (s)` / `duration
  (s)`, plus `+ Pulse` and a `Length` field (the `extend_length`). The timing
  diagram **updates live** as you edit; the status line turns green ("ok — N
  channels, length …") or red with the reason (e.g. "overlapping pulses on
  channel …"). Editing is validated with `to_lines()`, so an invalid sequence
  can't be run.
- **Export .py** — writes a `build_sequence()` file the viewer can open and
  other tools can import (exact round-trip).
- **Program + Run** — sends the sequence to the Pulser server (`new_sequence` →
  `add_ttl_pulse` → `program_sequence` → `start_single`). Needs the manager +
  Pulser server; prompts for the password, or uses the dashboard's shared
  connection when embedded. Editing and Export need no hardware.

## Notes

- Both are **dashboard panels** (declare `DASHBOARD_PANEL`), so they show up in
  `dashboard.py`. The viewer needs no connection; the editor uses the shared one
  only for Program+Run.
- Later (v3): drag pulses directly on the diagram, and a "show the live /
  last-programmed sequence" source.
