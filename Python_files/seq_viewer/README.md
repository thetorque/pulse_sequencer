# seq_viewer -- pulse-sequence timing-diagram viewer

*See* a pulse sequence before you run it. Each TTL channel is a lane whose
waveform steps high when the channel is on, across a shared time axis — a
logic-analyzer view of a `pulser3.Sequence`.

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

## Notes

- It's also a **dashboard panel** (declares `DASHBOARD_PANEL`), so it shows up in
  `dashboard.py` — handy to keep a sequence preview beside the controls. (It
  ignores the shared LabRAD connection; it needs none.)
- Read-only for now. A future v2 could add editing (drag pulses, a pulse table,
  Program + Run) and a "show the live/last-programmed sequence" source.
