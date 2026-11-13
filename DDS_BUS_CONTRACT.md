# DDS Backplane Bus — Protocol Contract (Step 0)

_v0.2, 2026-11-13 — all design decisions agreed (v0.1 was the draft). The shared
spec both FPGA tracks build against (see `NEXT_PHASE.md` → "Step 0"):_

- **Slave:** DDS ECP5 board — `VHDL_files/DDS_ECP5_2026_10_19/` (`bus_rx`, `dds_top`)
- **Master:** XEM7305 pulser — `VHDL_files/XEM7305_Pulser_2026_09_07/` (Phase 4, `0x81`)
- **Host:** `Python_files/pulser3` (M4 `dds.py`)

Items marked **✅ AGREED** were decided 2026-11-13; everything else is either
already true in hardware or follows directly from it.

---

## 1. Model (unchanged from the legacy system)

Each DDS board holds a **table of rows** (one row = one frequency/phase/amplitude
setpoint). Before a sequence the host writes each board's table. During the
sequence the pulser's TTL channels drive two **broadcast** lines to all boards:

| Pulser TTL channel | Backplane line | Effect on every board |
|---|---|---|
| `AdvanceDDS` (18) | `STEPNEXT` | apply the next row (`row_ptr += 1`) |
| `ResetDDS` (19) | `RAMRESET` | apply row 0 (`row_ptr = 0`) |

Row 0 is the state at sequence start and the idle state. The legacy parser
(`servers/pulser/sequence.py::parseDDS`) already produces exactly this: one row
per DDS change-time for every channel, an `AdvanceDDS` pulse per change, and a
`ResetDDS` pulse at the end. **That host logic carries over unchanged**; only
the row encoding and the transport change.

Manual / CW setting (no sequence) = write row 0, then `RESET` (§5).

---

## 2. Physical layer (verified 2026-11-13)

| Line | Use | Dir |
|---|---|---|
| `BACKPLANE_SCK` | frame clock | master → all |
| `BACKPLANE_MOSI` | frame data | master → all |
| `BACKPLANE_CS` | frame delimiter, active low | master → all |
| `BACKPLANE_STEPNEXT` | broadcast step (rising edge) | master → all |
| `BACKPLANE_RAMRESET` | broadcast reset (rising edge) | master → all |
| `BACKPLANE_AUX1-3` | reserved, master drives low | master → all |

- LVDS: DS90LV047A (master) → DIN41612 **row C, pins c3–c18** → DS90LV048A
  (every slave). Open/undriven pair reads **HIGH** (receiver fail-safe).
- **No return path** — the bus is write-only. Board status is visible only on the
  board's LEDs and its Pico sideband (§8).
- SPI **mode 0**, **MSB first**: MOSI changes on SCK falling, sampled on rising.
- **SCK = 25 MHz nominal, 33 MHz max.** Verified error-free 1–33 MHz
  (PRBS7, ~3e8 bits/rate, `bp_fast` / `bp_fast_rx`). The slave oversamples at
  ~155 MHz (OSCG DIV=2, ±15 %), so 25 MHz keeps ≥ 5 samples per SCK period.
- CS must be high for **≥ 200 ns** between frames. SCK idles low; SCK edges while
  CS is high are ignored.
- `STEPNEXT` / `RAMRESET`: active on the **rising edge**; pulse width **≥ 100 ns**
  (legacy pulses are 3 × 40 ns = 120 ns ✓). Slave edge-detect jitter ≈ 1 slave
  clock (~6.5 ns).

---

## 3. Row format (88 bits = 11 bytes, `config_ram` word)

| Bits | Field | Meaning |
|---|---|---|
| `[87:40]` | **FTW48** | AD9912 frequency tuning word: f = FTW·f_SYSCLK/2⁴⁸ (3.55 µHz @ 1 GHz) |
| `[39:24]` | **POW16** | phase = POW16/2¹⁶ × 360°. AD9912 uses the top 14 bits `[39:26]` |
| `[23:12]` | **VGA12** | MCP4821 code → ADL5330 gain (amplitude) |
| `[11:8]` | reserved | write 0 |
| `[7:0]` | **CTRL8** | bit 0 `RF_ON` (RF switch U10); bits 7:1 reserved, write 0 |

- **✅ AGREED — POW16 as a fraction of a turn** (instead of the raw 14-bit AD9912
  value that `ad9912_spi` uses today). It's host-friendly and survives a future
  DDS chip with more phase bits. Cost: `ad9912_spi` takes `row(39:26)` instead
  of `row(37:24)`.
- **✅ AGREED — amplitude = VGA code.** The AD9912 has no amplitude-scale register;
  output level is set by the VGA. Board 8 calibration: P_out ≈ −5 dBm +
  (V_GAIN − 0.88 V)/20.7 mV, V_GAIN = 2.048 V·code/4096 × 0.683, i.e. **~61
  codes/dB**, 0xB40 ≈ 0 dBm at 50 MHz. The **host** converts dBm → code with a
  per-board (later per-board, per-frequency) calibration table; the board never
  sees dBm. DAC full-scale current (FSC) is a **per-board constant**, set via
  `WRITE_REG` (§5), default 0x200.
- **✅ AGREED — `RF_ON` replaces the legacy "off = −37 dBm" convention.** With
  `RF_ON = 0` the board opens its RF switch (PE4251), which should isolate far
  better than the minimum VGA level (−49.8 dBm measured on board 8; switch
  isolation still to be measured). The legacy `off_parameters` map to `RF_ON = 0`.
- **✅ AGREED — no ramps.** The legacy rows also carried frequency/amplitude
  ramp rates (the AD9915's digital ramp generator, used by "Moving Lattice").
  The AD9912 has no ramp generator. v1 drops ramps; a later FPGA-driven FTW
  sweep could restore them using the reserved bits.

---

## 4. Frame format

One frame = one CS-low period. Bytes MSB first.

```
byte 0     : [7:5] = 000 (version)   [4:0] = ADDR
byte 1     : CMD
byte 2..   : payload (CMD-specific)
```

- **ADDR** — 5 bits, compared with the board's strapped address `add4..add0`.
  **`0x1F` = broadcast** (every board acts). So addresses 0–30 are usable.
- A board that doesn't match the address ignores the rest of the frame.
- A frame ends at CS rising. **A row/register is only committed when all of its
  bytes have arrived** — a truncated frame commits complete items only.
- A frame with an unknown CMD or a length that doesn't fit the CMD is ignored and
  counted as a frame error (§8).

---

## 5. Commands

| CMD | Name | Payload | Action |
|---|---|---|---|
| `0x01` | `WRITE_ROWS` | `START16` + N × 11-byte rows | write rows START, START+1, … (auto-increment). N is implied by the frame length. |
| `0x02` | `RESET` | — | same as a `RAMRESET` edge: row_ptr = 0, apply row 0 |
| `0x03` | `STEP` | — | same as a `STEPNEXT` edge |
| `0x04` | `WRITE_REG` | `REG16` + `DATA8` | raw AD9912 register write, followed by IO update (setup / FSC / debug) |
| `0x00` | `NOP` | any | ignored (padding) |

- `START16`, `REG16`: big-endian.
- **✅ AGREED — `RESET` / `STEP` as frames too.** They give the host a soft
  reset/step without the TTL lines (the host's `resetAllDDS` / `advanceAllDDS`),
  and a fallback while `RAMRESET` isn't wired on the bench coupler (c17/c18).
  Bus-command latency is a frame (~1 µs), so sequences still use the lines.
- Table depth: **8192 rows** (`ADDR_W = 13`; 8192 × 88 bits fits the LFE5U-25 EBR,
  ~40 of 56 blocks). START + N beyond the table wraps.

---

## 6. Step timing (slave behaviour)

To make a step fast and deterministic, the slave **preloads** the next row while
the current one is playing:

1. After applying row k, the slave streams row k+1 into the AD9912's **buffered**
   FTW/POW registers (one 10-byte SPI transaction) and the MCP4821's input
   register (`LDAC` held high).
2. On `STEPNEXT`: pulse AD9912 `IO_UPDATE` + MCP4821 `LDAC` together, update the RF
   switch from `CTRL.RF_ON` → row k+1 is live. Then preload row k+2.
3. On `RAMRESET` / `RESET`: load row 0 directly + update (not preloaded, so slower),
   then preload row 1.
4. After any `WRITE_ROWS` frame, re-preload row_ptr+1 (it may have been overwritten).

Resulting contract numbers:

| | Value | Note |
|---|---|---|
| Step latency, STEPNEXT edge → new FTW/POW | < 100 ns + AD9912 pipeline | edge detect + IO_UPDATE sync |
| **Minimum interval between steps** | **5 µs** ✅ | preload ≈ 2.5 µs (AD9912 SCLK ~39 MHz, MCP4821 ~16 MHz) + margin |
| Amplitude settling after a step | ~5 µs | MCP4821 settling (4.5 µs) + VGA; frequency/phase are much faster |
| `RESET` → row 0 live | ~5 µs | load + update |

A `STEPNEXT` arriving before the preload has finished is still applied as soon as
the preload completes (late, not lost) and is counted as a step-overrun (§8).
The **host** should reject sequences with DDS changes closer than 5 µs.

---

## 7. Master (XEM7305) side

- **BTPipeIn `0x81`** carries **length-prefixed raw frames**; the master is a dumb
  serializer and all protocol knowledge stays in the host:
  ```
  record = LEN16 (big-endian byte count) + LEN bytes of frame
  LEN = 0 → padding, skipped (pad the block to 16 bytes with zeros)
  ```
  The master asserts CS around each record's bytes, ≥ 200 ns CS-high gap between
  records, SCK = 25 MHz (`clk_100`/4 or `clk_200`/8).
- **✅ AGREED — length-prefixed raw frames** rather than the master building frames
  itself (legacy: WireIn `0x04` channel select + `0x81` row data). Keeps the FPGA
  trivial and lets new commands land as host-only changes. WireIn `0x04` becomes
  unused.
- `STEPNEXT` = sequencer channel 18 (`AdvanceDDS`) **OR** TriggerIn `0x40` bit 5.
- `RAMRESET` = sequencer channel 19 (`ResetDDS`) **OR** TriggerIn `0x40` bit 4.
  Trigger-generated pulses: ≥ 100 ns.
- `AUX1-3` driven low.

---

## 8. Error handling / status (slave)

The bus is write-only, so the slave can only **report locally**:

- Counters: frame errors, step overruns. Readable over the Pico sideband (later)
  and summarised on the LEDs (red = any error since reset).
- **✅ AGREED — no CRC in v1.** Measured BER < 1e-8 at 33 MHz; a full 8192-row
  table is ~720 kbit. Add a per-frame CRC-8 later if errors ever show up (it
  would need a readback path to be useful anyway).
- Power-up default: AD9912 initialised (0x0010 = 0xD0, FSC 0x200), row_ptr = 0, all
  rows zero → 0 Hz, VGA 0, **RF switch open**.

---

## 9. Host (`pulser3/dds.py`, M4) responsibilities

- Encode rows: FTW = round(f·2⁴⁸/f_SYSCLK), POW16, VGA code from the calibration
  table, `RF_ON`. f_SYSCLK per board (1 GHz direct for now).
- Program: per board `WRITE_ROWS(addr, start=0, rows…)`; one `0x81` write can carry
  frames for several boards.
- Sequence: keep the legacy `parseDDS` logic; enforce the 5 µs minimum DDS
  change spacing.
- Manual / CW: `WRITE_ROWS(addr, 0, [row])` + `RESET(addr)`.

---

## 10. Open questions

1. Is 5 µs minimum step spacing acceptable for the experiments? (Faster needs a
   faster slave clock: an ECP5 PLL at 200 MHz → AD9912 SCLK 50 MHz → ~1.6 µs.)
2. Per-frequency amplitude calibration: store on the host only (proposed), or
   also on the board?
3. Phase-coherent switching: does any experiment need the AD9912 phase
   accumulator cleared on a step (CTRL bit)? Needs a datasheet check.
4. Number of DDS boards in the final crate (address straps allow 31 + broadcast).
