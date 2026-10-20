# DDS ECP5 Board — Programming Guide (bitstream generation → programming)

Standalone handoff doc. If you're a fresh session reusing this board for **any**
project: this is everything needed to write gateware, build a bitstream, and load
it onto the FPGA. Nothing DDS-specific is required.

---

## 1. The board in one paragraph

- **FPGA:** Lattice **ECP5 `LFE5U-25F-6BG256C`** (caBGA-256). JTAG/SSPI **IDCODE = `0x41111043`**.
- **Config path:** an **on-board Raspberry Pi Pico W** configures the ECP5's volatile
  SRAM over **Slave-SPI** (the ECP5 is strapped `CFG[2:0]=001`). The Pico runs
  MicroPython; a script (`pico_sspi_load.py`, installed as `main.py`) does the loading.
- **Clock:** the ECP5 uses its **internal oscillator** (the `OSCG` primitive, ~310 MHz/DIV,
  DIV=2..128). There is **no external clock pin** — don't rely on one.
- **Powered from:** backplane 5 V; the Pico is powered from USB (bench) or the 5 V rail.
- **Config SRAM is volatile** — the FPGA must be re-programmed every power-up (the Pico
  does this automatically when `main.py` is installed).

Verification quick-check: a good load prints `READ_ID = 0x41111043` and `DONE = 1`.

---

## 2. One-time host setup (macOS)

Everything is macOS-native; **no Windows / no vendor tools** needed for the ECP5.

- **FPGA toolchain:** `oss-cad-suite` at `/Users/thanedp/Documents/oss-cad-suite`
  (provides `yosys` + the `ghdl` plugin, `nextpnr-ecp5`, `ecppack`, `openFPGALoader`, `ghdl`).
  Put its `bin/` on `PATH`. **GHDL-in-yosys needs** `export GHDL_PREFIX=/Users/thanedp/Documents/oss-cad-suite/lib/ghdl` (the Makefile sets this automatically).
- **Pico link:** `uv tool install mpremote`, then ensure `~/.local/bin` is on `PATH`
  (`echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc`). `mpremote` opens the
  MicroPython REPL (Ctrl-X to exit).
- **Pico firmware:** the Pico W must be running MicroPython. Flash the **`RPI_PICO_W`**
  UF2 from <https://micropython.org/download/RPI_PICO_W/> (BOOTSEL + drag the `.uf2`).

---

## 3. TL;DR — the whole flow

```bash
cd <this folder>                     # has the Makefile + dds_ecp5.lpf
make TOP=<name> compress             # <name>.vhd -> <name>_c.bit  (compressed bitstream)
mpremote cp <name>_c.bit :<name>_c.bit
mpremote exec "import main as L; L.BITFILE='<name>_c.bit'; L.program()"
```
Expect `READ_ID = 0x41111043` then `DONE = 1 -> SUCCESS`. Done.

For **persistent** auto-config at power-up, see §7.

---

## 4. Writing gateware for this board

Rules that keep you out of trouble on this board:

1. **Clock = `OSCG`** (internal). Instantiate it; there is no clock input pin.
2. **Drive every pin you use to a defined level.** An undriven ECP5 pin floats (weak
   pull) — on the active-low LEDs that shows as a dim glow. Declare the ports you use
   and drive the rest of what you care about.
3. **Pin names** come from the constraint file (`.lpf`); your top-level port names must
   match the `LOCATE COMP "<name>"` entries. The full board pin map is **`dds_ecp5.lpf`**
   (see §5). For a small design, make a small `.lpf` with just the pins you use.
4. All I/O banks are **3.3 V → `IOSTANDARD = LVCMOS33`**.

Minimal blinky template (`blink.vhd`) — internal clock, one output:
```vhdl
library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;
entity blink is port ( led : out std_logic ); end entity;
architecture rtl of blink is
  component OSCG generic ( DIV : integer := 128 ); port ( OSC : out std_logic ); end component;
  signal clk : std_logic;
  signal cnt : unsigned(21 downto 0) := (others => '0');
begin
  osc : OSCG generic map ( DIV => 128 ) port map ( OSC => clk );   -- ~2.4 MHz
  process(clk) begin if rising_edge(clk) then cnt <= cnt + 1; end if; end process;
  led <= cnt(21);     -- ~0.6 Hz
end architecture;
```
Matching constraint (`blink.lpf`), pick any pin from `dds_ecp5.lpf` (e.g. an LED):
```
LOCATE COMP "led" SITE "L16";
IOBUF  PORT "led" IO_TYPE=LVCMOS33;
```

(Verilog works too — `yosys` reads it natively; VHDL goes through the `ghdl` plugin.)

---

## 5. Pin map

The authoritative full-board pin definition is **`dds_ecp5.lpf`** (56 functional I/O,
generated from the board schematic). It also documents the pins you must NOT use as
fabric I/O:
- **Config pins (dedicated):** CCLK=N9, D0/MOSI=T8, D1/MISO=T7, SN/CSN=R8, PROGRAMN=R9,
  INITN=T9, DONE=P9 — handled by the Pico config path, not user logic.
- **JTAG:** TCK=T10, TMS=T11, TDI=R11, TDO=M10.
- **Mode straps:** CFG0=N10, CFG1=P10, CFG2=R10 (set to 001 = Slave SPI).

Handy groups in `dds_ecp5.lpf`: 12 status LEDs (active-low), 8 backplane lines, the
Pico sideband (SPI1), board-address straps, an AD9912 SPI port, a DAC/VGA SPI port.
Use whatever subset your project needs.

---

## 6. Build: source → bitstream

With the Makefile (recommended):
```bash
make TOP=<name>            # -> <name>.bit        (uncompressed)
make TOP=<name> compress   # -> <name>_c.bit      (compressed, for the Pico loader)
make TOP=<name> LPF=<file>.lpf   # override the constraint file
make clean
```
- Multi-file designs: add `SRC_<name> := a.vhd b.vhd <name>.vhd` (leaf modules first,
  top last) and `LPF_<name> := <name>.lpf` near the top of the Makefile.

Raw commands (if not using the Makefile), with `GHDL_PREFIX` exported:
```bash
yosys -m ghdl -p "ghdl --std=08 <srcs...> -e <top>; synth_ecp5 -json out.json"
nextpnr-ecp5 --25k --package CABGA256 --speed 6 --json out.json --lpf <lpf> --textcfg out.cfg
ecppack out.cfg out.bit            # add --compress for the compressed form
```
Device knobs: **`--25k --package CABGA256 --speed 6`** (this exact part).

**Bitstream size:** the uncompressed ECP5 `.bit` is a **fixed ~582 KB** for the -25
(independent of design). `--compress` gives ~0.1–0.4 MB; **use compressed** for the
Pico. (Designs that use a lot of EBR make the compressed file bigger — e.g. ~214 KB.)

---

## 7. Program the ECP5 (via the on-board Pico W)

The loader is **`pico_sspi_load.py`**. Two ways to use it:

**(a) One-shot** (configure now, doesn't persist):
```bash
mpremote cp <name>_c.bit :<name>_c.bit
mpremote exec "import main as L; L.BITFILE='<name>_c.bit'; L.program()"
```
`main.py` on the Pico is a copy of `pico_sspi_load.py`; importing it as `main` (not
`__main__`) runs `program()` once without the boot auto-run.

**(b) Persistent** (auto-configures on every power-up):
```bash
# edit BITFILE at the top of pico_sspi_load.py to your bitstream, then:
mpremote cp <name>_c.bit :<name>_c.bit
mpremote cp pico_sspi_load.py :main.py
```
MicroPython runs `main.py` at boot; it waits for rails, configures, retries. To stop
auto-config: `mpremote fs rm :main.py`.

**Expected output:** `READ_ID = 0x41111043 (LFE5U-25 OK)` then `DONE = 1 -> SUCCESS`.

**Pico filesystem is small (~0.8 MB total)** — delete old bitstreams if you hit
"No space left on device": `mpremote fs ls`, `mpremote fs rm :<old>.bit`.

### Alternative: JTAG (no Pico)
There is a bring-up JTAG header. With an external probe (FT2232, or a spare Pico
running DirtyJTAG) and `openFPGALoader -c <cable> <name>.bit` you can load to SRAM
directly. Handy for fast iteration, independent of the on-board Pico firmware.

---

## 8. The Slave-SPI programming sequence (reference)

If you ever need to re-implement the loader (different MCU/host), this is the exact,
hardware-verified AD-Lattice sequence `pico_sspi_load.py` performs. SPI **mode 0,
MSB-first, ≤ a few MHz**:

1. Pulse **PROGRAMN** low (~1 ms), release; wait **INITN** high.
2. *(optional)* `READ_ID` (0xE0 + 3 dummy, read 4) → expect `0x41111043`.
3. **`ISC_ENABLE` 0xC6** 00 00 00, ~1 ms.   ← required
4. **`ISC_ERASE` 0x0E** 00 00 00, ~10 ms.    ← required
5. CS low: **`LSC_BITSTREAM_BURST` 0x7A** 00 00 00, then the bitstream **starting at the
   `0xFFFF…BDB3` preamble** (skip the ecppack ASCII comment header!), then ~512 bytes
   `0xFF` trailing clocks; CS high.
6. **`ISC_DISABLE` 0x26** 00 00 00.
7. **Verify by the physical DONE pin = 1** (after ISC_DISABLE the SSPI status read
   returns 0 because the device entered user mode — that is normal).

Gotchas that cost real time here: (a) you MUST send ISC_ENABLE+ISC_ERASE before the
burst; (b) you MUST strip the comment header and start at the preamble; (c) stream the
bitstream with **CS held low throughout** (chunks are fine).

Pico config pin map: `GP2=SCK→CCLK, GP3=MOSI→D0, GP4=MISO→D1, GP5=CSn→SN,
GP6=PROGRAMN, GP7=INITN(in), GP8=DONE(in)`.

---

## 9. Simulation (optional, for logic you want to test first)

```bash
make sim TB=<tb_name>      # add SIM_SRC_<tb_name> := <srcs...> in the Makefile
```
- GHDL sim artifacts are kept in `/tmp` (gitignored).
- **`OSCG` does not clock in GHDL sim.** To simulate a top that instantiates OSCG,
  include **`sim_oscg.vhd`** (a sim-only OSCG model) in the sim sources — but NEVER in
  synthesis (nextpnr maps the real primitive). Prefer testbenching the sub-modules with
  an explicit clock.

---

## 10. File index (this folder)

| File | Purpose |
|---|---|
| `Makefile` | build (`make TOP=…[ compress]`), `make sim TB=…`, `make prog/flash` (JTAG) |
| `dds_ecp5.lpf` | **master pin map** (56 I/O) + config/JTAG pins to avoid |
| `pico_sspi_load.py` | the **Slave-SPI loader** (install as `main.py` for auto-boot) |
| `sim_oscg.vhd` | sim-only OSCG clock model (sim sources only) |
| `BRINGUP.md` | original full bring-up log + troubleshooting table |
| `*.vhd / *.lpf` | the DDS project's gateware + per-design constraints (examples to copy) |

---

## 11. Key facts cheat-sheet

- Part: `LFE5U-25F-6BG256C`; nextpnr `--25k --package CABGA256 --speed 6`; IDCODE `0x41111043`.
- Clock: `OSCG`, ~310 MHz/DIV (DIV 2..128); no external clock pin.
- I/O: LVCMOS33 (all banks 3.3 V). Drive unused pins to a defined level.
- Config: Pico W Slave-SPI; `main.py` = auto-boot loader; DONE pin high = success.
- Toolchain: oss-cad-suite; `GHDL_PREFIX=<oss>/lib/ghdl`.
- Uncompressed bitstream fixed ~582 KB; use `ecppack --compress` for the Pico.
- Pico fs ~0.8 MB — prune old bitstreams.
