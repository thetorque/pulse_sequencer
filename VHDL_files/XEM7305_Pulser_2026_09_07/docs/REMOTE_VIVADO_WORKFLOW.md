# Remote Vivado Build Workflow — XEM7305 Pulser

Self-contained handoff for any session (human or Claude) driving the XEM7305
FPGA build. This repo builds its bitstream **headlessly on a Windows bench PC,
triggered over SSH from a macOS dev machine** — you never open the Vivado GUI.

Proven end-to-end 2026-10-23: clean build, `build/photon.bit`, setup WNS +0.092 ns.

## Topology

- **Mac (dev)** — author HDL/XDC/TCL, git, trigger builds over SSH. Vivado does
  **not** run on macOS.
- **Windows bench** — `thanedp@192.168.1.113`, repo at
  `C:\Users\thanedp\Desktop\pulse_sequencer`, Vivado 2025.2, XEM7305 board
  attached via FrontPanel. SSH key-auth is set up (no password).
- **git is the Mac ↔ PC sync bus** — `origin` = github.com/thetorque/pulse_sequencer.
  Commit + **push** from the Mac before building; `build.bat` runs `git pull` on
  the PC first.

## Build scripts (committed)

- `VHDL_files/XEM7305_Pulser_2026_09_07/build.tcl` — headless synth → impl →
  `write_bitstream`. Opens `build/xem7305_pulser.xpr` if present (fast
  incremental), else creates it via `create_project.tcl`. Prints setup **WNS**,
  drops `build/photon.bit`, exits nonzero on failure. Args: `fresh` (recreate the
  project) / `clean` (reset the runs).
- `build.bat` (repo root) — portable wrapper: cd's to the repo, auto-detects the
  newest Vivado, `git pull`, runs `build.tcl`. No machine-specific paths.

Both `build/` (Vivado project + bitstream) and `src/ip/` (generated IP) are
gitignored — they're tool output, reproducible from `create_project.tcl`.

## Commands (run from the Mac shell)

Build — long, so run it in the background and wait for the completion notice:
```bash
ssh thanedp@192.168.1.113 "C:\Users\thanedp\Desktop\pulse_sequencer\build.bat"
```
Pass `fresh` / `clean` as `… build.bat fresh`.

Retrieve the bitstream:
```bash
scp thanedp@192.168.1.113:"C:/Users/thanedp/Desktop/pulse_sequencer/VHDL_files/XEM7305_Pulser_2026_09_07/build/photon.bit" ~/Downloads/
```

Program the attached board + hardware test (**touches hardware — confirm with the
user first**):
```bash
ssh thanedp@192.168.1.113 "cd C:\Users\thanedp\Desktop\pulse_sequencer\VHDL_files\XEM7305_Pulser_2026_09_07 && python test\smoke_test.py"
```

## Gotchas (learned the hard way)

1. **The bench SSH shell is `cmd.exe`.** Avoid complex cmd quoting / `&` chaining
   over SSH. Run a simple command and **filter on the Mac side with `grep`**, e.g.
   `ssh … "tasklist" | grep -i vivado`.
2. **Strip the benign OpenSSH warning** from output by piping through
   `grep -iv "warning\|post-quantum\|decrypt\|openssh.com\|upgraded"` — it's a
   harmless post-quantum-crypto notice on the LAN.
3. **Don't delete the Vivado `build/` tree with `rmdir` / `robocopy`.** Its
   `.runs\…` paths exceed Windows' 260-char limit, so the delete fails with "The
   system cannot find the path specified." You rarely need to — `build.tcl` opens
   the existing project. For a true from-scratch wipe, use a `\\?\`-prefixed
   long-path delete.
4. **WNS is tight (+0.092 ns).** This design's DDR3 read path is placement-
   marginal (see `STATUS.md` → "DDR3 read-path hardening" and the README). Watch
   the WNS line `build.tcl` prints on **every** build — a re-place can push it
   negative. Deferred fix: register the MIG return bus with `DONT_TOUCH`.
5. **Run builds in the background** (they take minutes); don't poll — you're
   notified on completion.
6. **Don't build while the Vivado GUI holds the project** — headless batch can't
   open a locked project. Check first: `ssh … "tasklist" | grep -i vivado`.

## One-time bench setup (already done; for reference / a new PC)

- Enable OpenSSH Server: `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0`;
  `Start-Service sshd`; `Set-Service sshd -StartupType Automatic`; allow TCP 22.
- Authorize the Mac's public key in
  `C:\ProgramData\ssh\administrators_authorized_keys` (admin account), then
  `icacls … /inheritance:r /grant Administrators:F /grant SYSTEM:F`.
- Clone the repo on the PC; confirm `build.bat` finds Vivado (`vivado -version`).

## Related docs

- `NEXT_PHASE.md` (repo root) — the phase plan + remote-build section.
- `STATUS.md` (this folder) — where every FPGA phase + the host/GUI stack stands.
- `README.md` (this folder) — per-phase detail, incl. the DDR3 read-path plan.
