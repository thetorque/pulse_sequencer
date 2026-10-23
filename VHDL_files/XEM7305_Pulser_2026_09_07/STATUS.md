# XEM7305 Master Pulser — Project Status vs Roadmap

_Snapshot: 2026-10-23. Verified against git history + `src/photon.vhd`, not memory._

This is the master/carrier pulser board (Opal Kelly **XEM7305**, Artix-7 FGG484,
on the **BRK7305** breakout). It is a phased port of the legacy XEM6010
`VHDL_files/Pulser_w_2015_07_28/photon/photon.vhd`. This file is the
one-page "where are we" summary spanning **PCB + FPGA gateware + host software**.

## TL;DR

- **Everything that can be tested without the DDS slave board is done and
  verified on real hardware** — both TTL pulse-sequencing paths (on-chip
  `pulser_ram` and the DDR3 streamer) and the PMT photon-counting logic.
- **The only missing capability is anything that physically talks to the DDS
  slave board** (Phase 4 DDS I/O, Phase 5c real PMT input pins, Phase 5d DDS
  step/reset routing, host M4). All of it is gated on DDS hardware + the
  carrier breakout pinout — not on unwritten logic.
- One non-DDS deferred item: the **DDR3 read path is placement-marginal** and
  wants a proper register fix (planned, not done).

---

## PCB (carrier board) — ✅ design complete

- Board review done 2026-10-05: **DRC clean, ERC benign.** Translator / LVDS
  driver / power / backplane all verified.
- Pin map fully resolved → XDC written (32 ports, all LVCMOS33). See the
  `xem7305-master-pinmap` memory and `docs/pcb_pin_plan.md`.
- I/O: 8 backplane bus lines (→ 2× DS90LV047A LVDS → DDS boards), 20 TTL out
  (3× SN74LVC8T245), 4 TTL in (1× '245), 8 status LEDs.
- Cosmetic leftover only: 2–3 signals on the VSYS plane — reroute to L1/L4 if
  convenient. Not blocking.

---

## FPGA gateware — phase-by-phase

`src/photon.vhd` currently instantiates (verified): `pmt_sim`, `pmt_counter`,
`pmt_diff_counter`, `pmt_timetagger`, `ddr3_line_streamer`, `pulse_sequencer`
(DDR3-fed) **and** the legacy `pulser_ram` FSM — **dual-path, selected by
`ep00wire(5)`** (1 = DDR3 sequencer, 0 = legacy on-chip RAM FSM).

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| **1** | Host interface migration (legacy endpoints → new okHost) | ✅ HW-verified | `test/smoke_test.py` |
| **2** | Clocking (MMCM → 200/100/20 MHz, measured 0.1%) | ✅ HW-verified | `smoke_test.py` |
| **3** | Pulse RAM/FIFO path (`pulse_fifo`→`pulser_ram` + 3 readout FIFOs) | ✅ HW-verified | `smoke_test.py` |
| **5a** | Main sequencer FSM + `logic_out` | ✅ HW-verified | `led_walk_demo.py` (lit `led_ext[0..5]`) |
| **5 (PMT) m1/m2** | Synthetic PMT source + normal-mode counter | ✅ HW-verified | `pmt_bringup.py` |
| **5 (PMT) m4a/b** | Time-resolved timetagger | ✅ HW-verified | `pmt_timetag_bringup.py` |
| **5 (PMT) m4d** | Differential (sequence-gated) counter | ✅ HW-verified (sim+HW) | wired `e6af77f` |
| **6a** | DDR3 MIG bring-up (calibrates vs real DDR3 chip) | ✅ HW-verified | `smoke_test.py` (`init_calib_complete`) |
| **6b** | DDR3 write-assembler + read-prefetch adapters | ✅ HW-verified | `ddr3_roundtrip_demo.py` |
| **6c** | DDR3 line streamer → FIFO → sequencer (dual-path) | ✅ HW-verified | `run_all_6c.py` **8/8 PASS**; `ddr3_sequencer_bringup.py` |

> **Note on PMT:** the counting *logic* (normal / timetag / differential) is
> proven, driven by the synthetic `pmt_sim` source. Wiring a *real* detector
> input is Phase 5c (blocked, below).

### Blocked on DDS slave board + carrier breakout pinout

| Phase | Scope | Why blocked |
|---|---|---|
| **4** | DDS I/O: `dds_fifo`, `dds_logic_*`, DDS program pipe **0x81** (currently a discard-everything stub) | DDS bus read clock is supplied by the DDS board itself; no DDS hardware yet |
| **5c** | Real PMT photon input pins (`pmt_input` / `logic_in`) | needs breakout board pinout |
| **5d** | DDS step/reset control routing (`AdvanceDDS`/`ResetDDS` triggers exist in host, not pinned) | needs breakout board + DDS board |

---

## Host software — ✅ TTL complete, DDS deferred

The modern (Python-3) control stack is built bottom-to-top and bench-verified:

```
PyQt5 GUIs ──LabRAD──► scalabrad servers ──► pulser3 driver ──► XEM7305
(pulser_gui,   (Pulser, ParameterVault,      (headless,
 seq_viewer)    ScriptScanner, NormalPMTFlow,  no Qt)
                DataVault)
```

- **`Python_files/pulser3/`** — headless Python-3 driver (no LabRAD/Twisted/Qt).
  M1–M3 + M1.5 **done, hardware-green.** Full path works:
  `hwconfig → Sequence → Driver → DDR3 → run single/finite/infinite`.
  **M4 (DDS host + PMT readout pipes 0xA0–0xA2 host side) deferred** — same DDS
  dependency.
- **`Python_files/pulser_labrad/`** — scalabrad `Pulser` server wrapping
  `pulser3`; sequencing + PMT + manual-switch, hardware-verified.
- **Modern LabRAD servers** (all py3-ported + bench-verified 2026-09-12):
  `parameter_vault/`, `script_scanner/`, `data_vault/` (HDF5), `pmt_flow/`
  (NormalPMTFlow), plus the `experiment/` layer framework.
- **`Python_files/pulser_gui/`** — **PyQt5** client framework (py3 port of the
  legacy py2/PyQt4 clients): `workbench.py` (tabbed Experiment Workbench),
  `switch_control.py`, `pmt_control.py`, `script_scanner_gui.py`,
  `parameter_editor.py`, shared `theme.py`. Uses pylabrad's **blocking** client
  (NOT qt5reactor). `seq_viewer/` adds the sequence editor/viewer (pyqtgraph);
  `dashboard/`, `grapher/`, `labrad_launcher/` round out the tooling.
- DDS-specific GUIs (legacy `clients/DDS_CONTROL.py`) stay DDS-hardware-blocked.

---

## Deferred / owed (not DDS-related)

**DDR3 read-path hardening — planned, not done.** After the 6c dual-path
integration, legacy-mode `memtest` showed transient one-beat corruption; root
cause is placement/timing marginality (sub-WNS-margin capture of the wide,
high-fanout MIG return bus in read state 2 of `photon.vhd`). The read-path
`dbg_*` diagnostics are currently **load-bearing** (their 128-bit register
happens to help the timing) and had to be restored. The real fix: register
`mig_app_rd_data`/`_valid` on `ui_clk` with `DONT_TOUCH`/`KEEP`, route every
consumer off the `_q` copies, keep `app_rdy`/`app_en` combinational. See the
"Roadmap — owed: DDR3 read-path hardening" section in `README.md` for the full
plan. **Risk:** any re-place (new Vivado run, added logic) can re-expose it.

---

## What to do next when the DDS board is ready

1. Define the carrier breakout pinout → unblocks Phase 4 / 5c / 5d constraints.
2. Phase 4: real `dds_fifo` + DDS program pipe 0x81 (replace the stub) + DDS
   logic output pins.
3. Host M4: port `dds.py` + PMT readout pipes; extend `hwconfig.py`
   (`AdvanceDDS`=18, `ResetDDS`=19 channels already reserved).
4. (Independent of DDS) Land the DDR3 read-path register fix before the next
   production bitstream re-place.
