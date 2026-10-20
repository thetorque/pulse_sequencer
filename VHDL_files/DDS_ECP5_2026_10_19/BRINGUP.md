# DDS Board Bring-Up Runbook — ECP5 via on-board Pico W (Slave-SPI)

**Status: WORKING (first light 2026-10-20).** The on-board Raspberry Pi Pico W
configures the ECP5 (LFE5U-25F-6BG256C) SRAM over Slave-SPI and drives the status
LEDs. This document is the complete procedure to bring up a **new** DDS board from
a bare, assembled PCB — including flashing the Pico, building the bitstream, and
loading it — plus the reference sequence and troubleshooting.

Board: `DDS_ECP5_pcb` (schematic/PCB).  Gateware + scripts: this folder
(`VHDL_files/DDS_ECP5_2026_10_19/`).

---

## 0. One-time host setup (do once per computer)

All macOS-native — **no Windows / Vivado needed** for the ECP5.

### 0a. FPGA toolchain (oss-cad-suite)
Already installed at `/Users/thanedp/Documents/oss-cad-suite`. It provides
`yosys` (+ghdl plugin), `nextpnr-ecp5`, `ecppack`, `openFPGALoader`, `ghdl`.
Ensure `oss-cad-suite/bin` is on `PATH` (the Makefile auto-derives `GHDL_PREFIX`).

### 0b. mpremote (talks to the Pico over USB)
```bash
uv tool install mpremote
# add ~/.local/bin to PATH (zsh). NOTE: ~/.zshenv is root-owned on this machine,
# so write to ~/.zshrc instead:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
mpremote           # should drop into the MicroPython >>> REPL; Ctrl-X to exit
```

---

## 1. Flash the Pico W with MicroPython (per board / per fresh Pico)

1. Download the **Pico W** build (not plain Pico): <https://micropython.org/download/RPI_PICO_W/>
   → grab the latest stable `RPI_PICO_W-*.uf2`.
2. Hold **BOOTSEL** on the Pico W while plugging USB in → it mounts as drive **RPI-RP2**.
3. **Drag the `.uf2`** onto RPI-RP2. It reboots; the drive disappears → MicroPython is running.
4. Verify: `mpremote` → MicroPython `>>>` REPL (Ctrl-X to exit).

> The production firmware will eventually be **C/C++ Pico SDK** (bitstream in a
> dedicated flash slot, config-at-boot). This MicroPython loader is for bring-up.

---

## 2. Build the bitstream

From this folder:
```bash
# default TOP is led_static; pick a design with TOP=
make TOP=led_half            # synth -> P&R -> ecppack -> led_half.bit
make TOP=led_half compress   # -> led_half_c.bit (~99 KB, for the Pico)
```
Designs available:
- `led_static` — all 12 LED elements ON (amber).
- `led_half`   — **only D1–D3 green** (distinctive config-verification pattern).
- `led_blink`  — OSCG-clocked green↔red flip (~0.6 Hz), proves fabric clock.
- `led_chase`  — running light sweeping left→right (physical order D5 D4 D1 D2 D3 D6),
  cycling colour each pass: green → red → amber → repeat. Exercises OSCG + both
  LED colours; uses physical-position ports (`led_pgN`/`led_prN`, see `dds_chase.lpf`).

Build chain (in the Makefile): `yosys -m ghdl` (VHDL via GHDL plugin) →
`synth_ecp5` → `nextpnr-ecp5 --25k --package CABGA256 --speed 6 --lpf dds_leds.lpf`
→ `ecppack [--compress]`.

> **Why compressed:** the Pico W has 2 MB flash / 264 KB RAM. The uncompressed
> `.bit` is 582 KB; compressed is ~99 KB, which fits both the MicroPython
> filesystem and RAM. The ECP5 decompresses on-chip (transparent to Slave-SPI).

---

## 3. Load the bitstream into the ECP5

```bash
mpremote cp led_half_c.bit :led_half_c.bit    # copy bitstream onto the Pico FS
mpremote run pico_sspi_load.py                # configure the ECP5
```
Expected:
```
READ_ID = 0x41111043 (LFE5U-25 OK)
DONE = 1  -> SUCCESS (bitstream running)
```
and the board shows **only D1–D3 green**.

To load a different design, edit `BITFILE` at the top of `pico_sspi_load.py`
(and `cp` that `_c.bit` to the Pico first).

> Config SRAM is **volatile** — it is re-loaded every power cycle. In production
> the Pico firmware runs this sequence automatically at boot (config FIRST, bring
> up WiFi AFTER, so the FPGA is live within a few hundred ms).

---

## 3b. Persistent auto-config at power-up (main.py)

MicroPython runs **`main.py`** from the Pico filesystem at every boot. Install the
loader as `main.py` and the Pico re-configures the ECP5 automatically on every
power cycle (no host, no commands):
```bash
mpremote cp led_chase_c.bit :led_chase_c.bit   # bitstream must be on the Pico FS
mpremote cp pico_sspi_load.py :main.py          # loader runs at boot
mpremote fs ls                                  # verify: main.py + *_c.bit present
```
The loader's `__main__` adds a ~250 ms rail-settle delay + 3 retries for a reliable
cold boot. **Verified 2026-10-20:** USB disconnected, cycle the backplane 5 V →
LEDs start running in **< 1 s** from a blank FPGA.

**Power topology note (Q4 P-FET, USB-priority):** whichever is higher — USB VBUS or
backplane 5 V — powers the Pico. So to see an auto-config, the **Pico** must reboot:
cycle the **backplane 5 V with USB disconnected** (both Pico+ECP5 reboot), or
unplug/replug USB. Cycling the backplane while USB stays connected keeps the Pico
powered, so `main.py` does not re-run.

To change the boot bitstream, edit `BITFILE` in `pico_sspi_load.py`, re-`cp` it as
`main.py`, and `cp` the new `*_c.bit`. To stop auto-config, `mpremote fs rm :main.py`.

---

## 4. Hardware reference

### 4a. Config port (Pico W GPIO ↔ ECP5 ball) — verified from the DDS netlist
| Pico pin | GPIO | Net | ECP5 ball / function | Notes |
|---|---|---|---|---|
| 4 | GP2 | PICO_W_SCK | **N9** CCLK | via R30 33 Ω series; R28 1 k pull-up is DNP |
| 5 | GP3 | PICO_W_MOSI | **T8** D0/MOSI | |
| 6 | GP4 | PICO_W_MISO | **T7** D1/MISO | |
| 7 | GP5 | PICO_W_CS | **R8** SN/CSN | 4k7 pull-up R27 |
| 9 | GP6 | PICO_W_PROGRAMN | PROGRAMN | |
| 10 | GP7 | PICO_W_INITN | INITN (open-drain) | |
| 11 | GP8 | PICO_W_DONE | DONE | |

**Mode straps: CFG[2:0] = 001 = Slave SPI** — CFG_0 (N10) pull-up **R18 = 4k7 to
3V3 (POPULATED)**; CFG_1 (P10) = GND; CFG_2 (R10) = GND. SPI mode 0 (CPOL=0,
CPHA=0), MSB-first, works 0.5–8 MHz.

(Separate from config: sideband SPI1 = GP10–13 + GP9 ATTN; OLED I²C1 = GP14/15.)

### 4b. Status LEDs (6 bicolor D1–D6, common-anode to 3V3 → ACTIVE-LOW: '0'=ON)
| LED | Green ball | Red ball |
|---|---|---|
| D1 | G1 L16 | R1 K15 |
| D2 | G2 K16 | R2 J15 |
| D3 | G3 J16 | R3 H15 |
| D4 | G4 M16 | R4 L15 |
| D5 | G5 N16 | R5 M15 |
| D6 | G6 G15 | R6 G16 |

All in 3.3 V banks → **LVCMOS33**. Unconfigured ECP5 I/O are high-Z → all LEDs dark.

---

## 5. The Slave-SPI configuration sequence (reference)

After a PROGRAMN pulse and INITN high, each command is its own CS-low cycle
(opcode + 24-bit operand = 4 bytes), **except the burst** which is one continuous
CS-low transaction:

1. *(optional)* `READ_ID` **0xE0** → expect **0x41111043** (proves the link).
2. **`ISC_ENABLE` 0xC6** 00 00 00, wait ~1 ms.  ← essential (enter programming mode)
3. **`ISC_ERASE` 0x0E** 00 00 00, wait ~10 ms.  ← essential (clear config SRAM)
4. **`LSC_BITSTREAM_BURST` 0x7A** 00 00 00, then **immediately** (same continuous
   `spi.write`, no clock gap) the bitstream **starting at the `FFFF…BDB3`
   preamble**, then ~512 bytes `0xFF` trailing clocks. CS high.
5. **`ISC_DISABLE` 0x26** 00 00 00 → device enters user mode, **DONE pin → 1**.

**Verify success by the physical DONE pin = 1**, NOT the status register — after
`ISC_DISABLE` the SSPI `READ_STATUS` returns `0x00000000` because the device left
config-access mode (this is normal). During a healthy burst the status shows
`StdPreamble=1` (bit 21) and `DONE=1` (bit 8).

**Bitstream prep:** the ecppack `.bit` begins with an ASCII comment header
(`"Part: LFE5U-25F-6CABGA256\0"`) *before* the preamble. In Slave-SPI the device
parses pre-preamble bytes as commands (→ InvCmd error), so the loader finds
`0xBDB3`, backs up over the `0xFF` padding, overwrites the 4 bytes just before it
with `7A 00 00 00`, and streams from there (one buffer, one transaction).

---

## 6. Troubleshooting (every failure mode we hit, and the fix)

| Symptom | Cause | Fix |
|---|---|---|
| `mpremote: command not found` | `~/.local/bin` not on PATH | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc` |
| `uv tool update-shell` → permission denied on `~/.zshenv` | `.zshenv` is root-owned | write to `~/.zshrc` instead (above); optionally `sudo chown thanedp:staff ~/.zshenv` |
| MicroPython REPL shows `SyntaxError` on shell commands | you typed shell cmds **inside** the REPL | Ctrl-X to exit REPL; run `mpremote cp/run` at the zsh `%` prompt |
| `ERROR: [Errno 2] ENOENT` | bitstream not on **this** Pico's FS (e.g. after swapping modules) | `mpremote cp led_half_c.bit :led_half_c.bit` first |
| `MemoryError: allocating ~98826 bytes` | two 99 KB copies in RAM (`bytearray(f.read())` or `buf[x:]` slice) | read into a pre-sized `bytearray` with `f.readinto`; use `memoryview` slices |
| `READ_ID = 0x00000000`, but PROGRAMN/INITN/DONE handshake works | **faulty Pico module** (dead SPI GPIO2–5) | swap the Pico W; confirm with `pico_sspi_bitbang.py` (bit-bang READ_ID) |
| config streams but `StdPreamble=0`, `status=0` | missing `ISC_ENABLE`/`ISC_ERASE`, or comment header sent | use the full sequence (§5); strip to the preamble |
| raw-stream `status=0x10000000` (`InvCmd=1`) | device in command mode choking on the `.bit` ASCII header / `0xBD` | must send `ISC_ENABLE`→`ISC_ERASE`→`0x7A`+data, not a raw stream |
| GHDL in yosys: "cannot find std library" | `GHDL_PREFIX` unset | Makefile sets it; else `export GHDL_PREFIX=<oss-cad-suite>/lib/ghdl` |

**Diagnostic scripts** (in this folder, run with `mpremote run <name>`):
- `pico_sspi_bitbang.py` — bit-bang READ_ID (hardware-vs-software split; no peripheral).
- `pico_sspi_status.py` / `pico_sspi_cont.py` — stream + decode the status register.
- `pico_sspi_flow.py` — the full flow with per-step status (what proved the fix).

---

## 7. File inventory (this folder)

| File | Purpose |
|---|---|
| `led_static.vhd` / `led_half.vhd` / `led_blink.vhd` | test gateware (all-on / D1–D3 green / blink) |
| `dds_leds.lpf` | ECP5 pin constraints (LED balls, LVCMOS33) |
| `Makefile` | build: `make TOP=<name> [compress]`, `make prog` (JTAG), `make flash` |
| `*_c.bit` | compressed bitstreams for the Pico loader |
| `pico_sspi_load.py` | **the working Slave-SPI loader** (run this) |
| `pico_sspi_*.py` (bitbang/status/cont/flow/diag) | bring-up diagnostics |
| `README.md` | short overview |
| `BRINGUP.md` | this runbook |

---

## 8. Next steps (beyond this bring-up)
- Port the loader to the **C/C++ Pico SDK** (production firmware): bitstream in a
  dedicated flash slot, config-at-boot, golden fallback image, WiFi after config.
- Then the real DDS gateware: pulser-bus receiver → config RAM → AD9912 SPI
  streamer (per [[dds-slave-board]]), once the AD9912 is populated.

*(Alternative loader path: a JTAG header + a spare Pico running DirtyJTAG +
`openFPGALoader -c dirtyJtag` loads straight to SRAM — handy for fast iteration,
independent of the on-board Pico firmware.)*
