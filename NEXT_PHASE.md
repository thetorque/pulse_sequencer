# Next Phase — Development Plan

_Planning doc, 2026-10-23. How to run the three parallel dev tracks (DDS ECP5
board · XEM7305 master · GUI + LabRAD) across a macOS dev machine and a Windows
bench. Companion to `VHDL_files/XEM7305_Pulser_2026_09_07/STATUS.md` (where each
track stands today)._

## Goal of this phase

Close the last gap in the stack: **the DDS slave board talking to the XEM7305
master over the backplane**, end to end, driven from the host GUIs. Concretely:

- **DDS ECP5 board** — finish `bus_rx`, integrate `dds_top`, populate the AD9912,
  scope-verify a programmed frequency/phase/amplitude.
- **XEM7305 master** — Phase 4 DDS bus master (`dds_fifo` + real `0x81` program
  pipe, replacing the stub); plus the deferred DDR3 read-path register fix.
- **GUI + LabRAD** — host M4 (`dds.py` + PMT readout pipes), then the DDS control
  GUI; harden the existing switch/PMT/scanner GUIs live on the bench.

Everything that does **not** touch the DDS board is already hardware-verified
(both TTL sequencing paths + PMT counting) — see STATUS.md.

---

## Machine roles (hybrid topology)

Decided 2026-10-23: **Windows bench** = hardware host; **macOS** = dev + ECP5.
Don't consolidate onto the PC — only Vivado and the board-attached pieces are
pinned there; keep the fast dev loop on the Mac.

| | **macOS (dev machine) — "dev + ECP5"** | **Windows bench — "hardware host"** |
|---|---|---|
| DDS ECP5 gateware | build + GHDL sim + program via Pico/USB | (only if the DDS board is wired here) |
| XEM7305 gateware | **author** HDL / XDC / TCL only | **Vivado build + FrontPanel program + `ok` HW tests** |
| LabRAD servers | author; run pure servers if useful | **scalabrad manager + Pulser (board) + DataVault / ParameterVault / ScriptScanner / NormalPMTFlow** |
| PyQt5 GUIs | author **and run** (→ bench manager over TCP) | not needed (no PyQt on the bench) |
| git | author + commit | pull + build + test (+ commit bench fixes) |

**The only hard constraints:** Vivado has no macOS build, and the board-attached
pieces (FrontPanel, Pulser server) must run where the XEM7305 is plugged in.
Everything else is portable.

---

## The two sync mechanisms

### 1. git is the Mac ↔ Windows bus
Remote: `origin` = `github.com/thetorque/pulse_sequencer`.
Flow: **Mac authors + commits → push → Windows `git pull` → build/test → report**
(bench-verified fixes commit on Windows → Mac pulls back).

> As of 2026-10-23 `master` is **ahead of `origin/master`** (this session's ECP5
> + docs commits are unpushed). Push to light up the bench before starting.

### 2. LabRAD is networked — run the GUIs on the Mac against the bench
The board-attached Pulser server + manager stay on Windows; GUI iteration stays
on the Mac. The GUIs already do env-then-login-prompt (see
`Python_files/pulser_gui/`).

On the Mac:
```bash
export LABRADHOST=<bench-windows-ip>
export LABRADPASSWORD=<pw>
export LABRAD_TLS=off
python Python_files/pulser_gui/workbench.py
```
Prereq: open the scalabrad **manager port 7682** on the Windows firewall.

---

## Sequencing — contract first, then two FPGA tracks in parallel

The three tracks are **not** independent: the DDS backplane bus is a shared
contract between the ECP5 (slave, `bus_rx`) and the XEM7305 (master, `dds_fifo` +
`0x81`). Both ends must agree on the wire format before either can be finished.

```
Step 0: DDS backplane protocol contract  ─┬─► A (ECP5): bus_rx → dds_top integ → AD9912 populate + scope
                                          └─► B (XEM7305): Phase-4 DDS master (dds_fifo + real 0x81)
                                                     │
            (both meet at)  ►  BENCH INTEGRATION: XEM7305 streams a word → ECP5 bus_rx → config_ram → AD9912 out
                                                     │
                                                     └─► C: host M4 (dds.py) → DDS_CONTROL GUI port

Parallel "fill" work (no cross-dependencies, do anytime):
  • B': XEM7305 DDR3 read-path register fix (the deferred item in STATUS.md)
  • C': harden existing switch/PMT/scanner GUIs live on the bench
```

**Critical path:** contract → (bus_rx ∥ Phase-4) → bench integration → M4 → DDS GUI.

### Step 0 — the DDS backplane protocol contract (the linchpin)
Write this first, as its own short spec both FPGA tracks build against. It must
define:
- **Wire format** over the already-pinned backplane bus (`BACKPLANE_SCK / MOSI /
  CS / STEPNEXT / RAMRESET / AUX1-3`). (The carrier pin map already places all 8
  lines — the DDS bus is **not** gated on a breakout board.)
- **Word → row mapping:** how a host DDS word lands as an 88-bit `config_ram` row
  (`[87:40]=FTW48 · [39:24]=POW16 · [23:8]=AMP16 · [7:0]=CTRL8`), then streams to
  the AD9912 (ad9912_spi already writes POW+FTW from this row).
- **Addressing:** board select via `add0-4`; `STEPNEXT` advances `row_ptr`;
  `RAMRESET` semantics.
- **Host side:** how the `0x81` BTPipeIn payload on the XEM7305 maps onto the
  backplane stream.

---

## Per-track detail

### Track A — DDS ECP5 board  (dev loop: all on Mac)
Folder: `VHDL_files/DDS_ECP5_2026_10_19/` · build/program guide: `PROGRAMMING.md`
- `bus_rx.vhd` — **still a stub** (`we<='0'`). Implement to the Step-0 contract:
  decode the backplane stream, write rows into `config_ram`.
- `dds_top` integration testbench — wire the full datapath in GHDL sim.
- Hardware: measure rails, then **populate the AD9912** (QFN reflow), scope-verify
  `ad9912_spi` pins and a programmed tone.
- Loop: `make TOP=… compress` → `mpremote` program via Pico → verify. Fast, local.

### Track B — XEM7305 master  (author on Mac, build/test on Windows)
Folder: `VHDL_files/XEM7305_Pulser_2026_09_07/` · status: `STATUS.md`
- **Phase 4 DDS bus master:** real `dds_fifo` (its read clock comes from the DDS
  board), replace the `0x81` discard stub, drive the backplane per the contract.
- **B' (independent) DDR3 read-path register fix:** register `mig_app_rd_data` /
  `_valid` on `ui_clk` with `DONT_TOUCH`/`KEEP`, route every consumer off the
  `_q` copies (see the "DDR3 read-path hardening" section in that folder's
  `README.md`). Land this before the next production re-place.
- Loop: Mac edits HDL/XDC/TCL → push → Windows `create_project.tcl` build in
  Vivado → FrontPanel program → `python test/…` → report. (`create_project.tcl`
  is already headless and Mac↔Windows-clean, commit `b2325ca`.)

### Track C — GUI + LabRAD  (author + run on Mac; servers on Windows)
Folders: `Python_files/pulser_gui/`, `pulser3/`, `pulser_labrad/`, servers.
- **C' (independent, anytime):** bench-verify + harden the existing GUIs
  (switch / PMT / scanner / parameter / workbench) against the live manager —
  run them from the Mac over the network.
- **M4 (needs Track B working):** port `dds.py` into pulser3 + the PMT readout
  pipes `0xA0–0xA2` host side. `hwconfig.py` already reserves `AdvanceDDS`=18,
  `ResetDDS`=19.
- **DDS GUI (needs M4):** port the legacy `clients/DDS_CONTROL.py` to the
  PyQt5 / blocking-client style (frequency/phase/amplitude per DDS channel).

---

## Claude (macOS dev session) — what I do vs. what needs the bench

- **I can, here:** author all three tracks; build + GHDL-sim the ECP5; write the
  Vivado HDL/XDC/TCL for headless Windows builds; write + Mac-verify (compile /
  unit / sim) the py3 servers and PyQt5 GUIs; manage git.
- **Needs the bench (you run, I interpret):** Vivado synth/impl, FrontPanel
  programming of the XEM7305, any `ok`-module hardware test, live GUI runs
  against real hardware, the AD9912 reflow + scope work.
- Working pattern (as the whole project has run): I author + Mac-verify → you
  build/test on the bench → report back → iterate.

---

## Remote build over SSH (Track B workflow)

The Windows bench doubles as a headless build + program server, driven from the
Mac — no need to sit at the PC for builds.

**One-time PC setup:** enable OpenSSH Server (`Add-WindowsCapability -Online -Name
OpenSSH.Server~~~~0.0.1.0`; `Start-Service sshd`; `Set-Service sshd -StartupType
Automatic`), allow TCP 22 on the LAN firewall, and authorize the Mac's public key
in `C:\ProgramData\ssh\administrators_authorized_keys` (admin account) with
`icacls … /inheritance:r /grant Administrators:F /grant SYSTEM:F`.

**The build scripts (checked in):**
- `build.tcl` (in the XEM7305 folder) — headless synth → impl → `write_bitstream`,
  opens the project if it exists else creates it via `create_project.tcl`, prints
  setup **WNS**, drops `build/photon.bit`, exits nonzero on failure. Args:
  `fresh` / `clean`.
- `build.bat` (repo root) — portable wrapper: cd's to the repo, auto-detects the
  newest Vivado, `git pull`, runs `build.tcl`. No machine-specific paths.

**From the Mac:**
```bash
# build on the bench (PC pulls latest, builds, prints WNS + bitstream path)
ssh <user>@<bench-ip> "C:\path\to\repo\build.bat"
# retrieve the bitstream
scp <user>@<bench-ip>:"C:/path/to/repo/VHDL_files/XEM7305_Pulser_2026_09_07/build/photon.bit" ~/Downloads/
# later: program the attached board remotely
ssh <user>@<bench-ip> "cd C:\path\to\repo\VHDL_files\XEM7305_Pulser_2026_09_07 && python test\smoke_test.py"
```
First build is slow (regenerates all IP incl. MIG); later builds are incremental.
Loop: Mac edits HDL/XDC → commit → **push** → ssh-trigger build → scp the bitstream
→ ssh-trigger program/test.

## Prereqs / open items before dev starts

- [ ] Push the unpushed `master` commits so the bench can pull.
- [ ] Open scalabrad manager port **7682** on the Windows firewall (for Mac GUIs).
- [ ] Confirm the Windows bench Vivado + FrontPanel + scalabrad env still runs
      (the `JAVA_HOME` / corrupt-registry fixes are documented in
      `Python_files/pulser_labrad/manual.html`).
- [ ] **Write the Step-0 DDS backplane protocol contract** (its own doc) — the
      first dev task; unblocks Tracks A and B in parallel.
- [ ] AD9912 population plan for the DDS board (QFN reflow) before Track A HW.
