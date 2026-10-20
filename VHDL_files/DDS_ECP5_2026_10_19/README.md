# DDS ECP5 — Phase-1 LED bring-up (2026-10-19)

First-light test for the LFE5U-25F-6BG256C on the new DDS board. No AD9912 needed.
Goal: prove the FPGA + power + config path by driving the on-board status LEDs.

> **STATUS (2026-10-20): first light achieved** — the on-board Pico W configures
> the ECP5 over Slave-SPI (`pico_sspi_load.py`), LEDs confirmed. For the complete
> new-board procedure (flash Pico, build, load, troubleshoot) see **[BRINGUP.md](BRINGUP.md)**.

## Hardware
- 6 bicolor LEDs (D1–D6, LTST-S326KGJRKT), **common anode → P3.3V → ACTIVE-LOW**
  (`'0'` = element ON, sinks through 1 kΩ).
- Ball map (from `DDS.kicad_sch`, U1C/U1D):

  | LED | Green → ball | Red → ball |
  |-----|--------------|------------|
  | D1  | LED_G1 L16   | LED_R1 K15 |
  | D2  | LED_G2 K16   | LED_R2 J15 |
  | D3  | LED_G3 J16   | LED_R3 H15 |
  | D4  | LED_G4 M16   | LED_R4 L15 |
  | D5  | LED_G5 N16   | LED_R5 M15 |
  | D6  | LED_G6 G15   | LED_R6 G16 |

  All in 3.3 V banks → LVCMOS33.

## Prereqs
- `oss-cad-suite` on PATH (yosys+ghdl plugin, nextpnr-ecp5, ecppack, openFPGALoader).
- A JTAG probe on the board's JTAG header: a spare Pico running **DirtyJTAG**
  (default `PROBE=dirtyJtag`), or an FT2232 (`make PROBE=ft2232 ...`).

## Order of operations
0. **Rails first** (meter 1.1 V core, 2.5 V VCCAUX, 3.3 V VCCIO; DONE should be low).
1. **Static test** — all LEDs on (amber). Proves config + all 12 I/O + LED network:
   ```
   make TOP=led_static prog
   ```
2. **Blink test** — bicolor flip green↔red ~0.6 Hz via OSCG. Proves fabric clock + logic:
   ```
   make TOP=led_blink prog
   ```
Both load to **SRAM** (volatile). Re-run `prog` to iterate; nothing is written to flash.
Use `make ... flash` only once a bitstream is final.

## Notes
- `led_blink` instantiates `OSCG` (internal ~310 MHz osc / 128 ≈ 2.4 MHz) — zero
  external-clock dependency. If GHDL warns that component `OSCG` is "not bound",
  that is expected (it is a vendor black box); nextpnr-ecp5 maps it.
- Device/package/speed in the Makefile: `--25k CABGA256 --speed 6`.
