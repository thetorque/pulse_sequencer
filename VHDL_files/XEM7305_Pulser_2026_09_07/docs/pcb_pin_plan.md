# XEM7305 carrier-board routing plan (pulser)

What the pulser design needs brought out of the **XEM7305** (Artix-7
`XC7A75T-FGG484`) onto a new carrier/breakout PCB. Every breakout in
`PCB_designs/` is for the old **XEM6010 / Altera** boards, so this mapping is
being defined from scratch for the 7305.

**Status of the FPGA-pin column:** the *signal side* below is authoritative (from
the legacy `Pulser_w_2015_07_28/photon/photon.vhd` entity + `Pin_connection.xlsx`
+ the 2026 `photon.vhd`). The **Artix-7 pin numbers are NOT filled in** because
the XEM7305 expansion-connector → FPGA-pin table isn't in this repo — get it from
the **Opal Kelly XEM7305 User's Guide ("Expansion Connectors" / JP2 & JP3)** or
its pin CSV, then fill the "FPGA pin" / "Conn pin" columns. Do **not** guess pins.

> The 2026 bitstream currently drives the sequencer's 32-bit `master_logic` only
> to `led`/`led_ext` as a stand-in — the real `logic_out[31:0]` / `pmt_input` /
> `logic_in` ports (present in the legacy entity) are **not pinned yet**. Adding
> them + this XDC is the "breakout board" step the code comments refer to.

## 1. Signals to route (the carrier's job)

| Group | Signals | Count | Dir (FPGA) | Level on carrier | Notes |
|---|---|---:|---|---|---|
| **TTL pulse outputs** | `logic_out[31:0]` | 32 | out | 3.3V → **5V TTL** | main pulse channels; buffer/level-translate 3.3→5V. Names per `pulser3/hwconfig.py` (ttl_0, sMOT_PROBE, … 0-11 used; 16 = DiffCountTrigger; 18/19 DDS adv/reset; 20-23 AO/B-field; 24 clock). |
| **PMT input** | `pmt_input` | 1 | in | **5V TTL → 3.3V** | **fast: 5-7 ns pulses.** Put on a clock-capable / low-skew pin; keep the trace short, translator must pass ~5 ns. |
| **Logic inputs** | `logic_in[3:0]` | 4 | in | 5V → 3.3V | `logic_in(0)` = **line trigger** (conditioned on-board in legacy: debounce → user delay). Others = aux / external trigger. |
| **Aux clock in** | `aux_clk_in` | 1 | in | 5V → 3.3V | external reference; route to a **clock-capable (MRCC/SRCC)** pin. |
| **DDS bus** *(deferred)* | see sub-table below | 26 | mixed | 3.3V | to the separate DDS board; **DDS hardware not built** — route the header now if convenient, not needed for current firmware. All lines pass **inverted** (`not`) across the interface. |
| **I²C** | `i2c_sda`, `i2c_scl` | 2 | — | 3.3V | **UNUSED** — the legacy FPGA only tri-states these (`<= 'Z'`), no controller. Provisioned-but-never-used bus. **Drop unless you plan an on-carrier I²C device** (level-translator config, DAC, temp sensor, EEPROM); optional 2-pin header at most. |

### DDS bus detail (26 pins, to the DDS board — deferred)

| Signal | Count | Dir (XEM) | Meaning |
|---|---:|---|---|
| `dds_logic_data_out[15:0]` | 16 | out | 16-bit DDS instruction word streamed from `fifo_dds` |
| `dds_logic_address[3:0]` | 4 | out | DDS channel/chip select (host WireIn 0x04) |
| `dds_logic_fifo_rd_clk` | 1 | **in** | read clock **from the DDS board** — needs a **clock-capable pin** |
| `dds_logic_fifo_rd_en` | 1 | **in** | read-enable from the DDS board (pop next word) |
| `dds_logic_fifo_empty` | 1 | out | FIFO-empty flag to the DDS board |
| `dds_logic_ram_reset` | 1 | out | reset DDS RAM — `master_logic(19)` (`ResetDDS`) or host ep40(4) |
| `dds_logic_step_to_next_value` | 1 | out | advance DDS — `master_logic(18)` (`AdvanceDDS`) or host ep40(5) |
| `dds_logic_reset_dds_chip` | 1 | out | hard-reset DDS chip(s) — host ep40(6) |

The DDS board **pulls** words out of the main FPGA's FIFO (hence `rd_clk`/`rd_en`
are inputs); `step_to_next_value`/`ram_reset` are driven by the running pulse
sequence (`master_logic` bits 18/19), so they're timing-relevant.

**Total user I/O (excluding DDS/i2c):** 32 out + 1 PMT + 4 in + 1 clk = **38 pins**.
With DDS + i2c: ~66.

### XEM7305 expansion capacity (from Opal Kelly docs)

Two 80-pin connectors (**MC1**, **MC2**; Samtec BSE-040-01-F-D-A) carry **108
usable FPGA I/O** — plenty for the 38 core pins, and even the full ~66 with DDS.

| FPGA bank | Connector | I/O | VCCIO |
|---|---|---:|---|
| Bank 15 | MC1 | 50 | `VCCO_MC1` (MC1-12/13) |
| Bank 34 | MC2 | 48 | `VCCO_MC2` (MC2-41/42) |
| Bank 16 | MC2 | 10 | `VCCO_MC2` |

- **Set VCCIO to 3.3 V** for the LVCMOS33 pulser I/O by powering `VCCO_MC1` /
  `VCCO_MC2` at 3.3 V (bank 15 alone = 50 pins, enough for all 32 TTL on one
  connector).
- **MRCC clock-capable pins** (use for PMT-in, aux-clk-in, DDS `fifo_rd_clk`):
  bank 15 → D14/D15 (MC1-49/51), F14/F15 (MC1-67/69); bank 34 → R3/T2 (MC2-75/77).
- MC2 also carries **JTAG** (TCK/TMS/TDI/TDO) and **XADC** (VP/VN) — avoid those.
- **Authoritative per-pin table + XDC generator:** the *Opal Kelly Pins* interactive
  reference for the XEM7305 (docs.opalkelly.com → XEM7305 → Expansion Connectors).
  Export/screenshot that table (MCx ↔ FPGA pin ↔ bank) to fill the columns below.

## 2. XEM7305 pins already committed — DO NOT reuse

From the working `constraints/xem7305.xdc`:

| Function | Where it goes | Route on carrier? |
|---|---|---|
| FrontPanel host (`okHU/okUH/okUHU/okAA/okRSVD`) | on-module (FX3 USB) | **No** — on the SoM |
| DDR3 (`ddr3_*`, banks 34/35 @ 1.5V SSTL) | on-module DDR3 | **No** — on the SoM |
| `sys_clk_p/n` (R2/R1, LVDS) | on-module 100 MHz osc (DDR3 ref) | **No** |
| `led[0]`,`led[1]` (J5/G6, 1.5V) | on-module LEDs | No |
| `led[2]`,`led[3]` (R12/L13, 1.8V) | **expansion** | already pinned (free to repurpose) |
| `led_ext[5:0]` (V2,T4,T5,P5,P2,R4, **LVCMOS33**) | **expansion** | already pinned — currently the pulse-channel stand-in; these 6 are known-good 3.3V expansion pins you can reuse as the first TTL outs |

So `led_ext[5:0]` gives you **6 confirmed 3.3V expansion pins** today; the other
~32 needed pins come from the expansion table.

## 3. Electrical notes (carry over from the legacy carrier)

- **Level translation both ways:** FPGA I/O is 3.3V (expansion banks), lab TTL is
  5V. Legacy used translators on every line ("5V through level translator to 3.3V"
  for PMT/TRIGGER/AUX inputs; outputs buffered up to 5V). Plan translator ICs +
  their VCC on the carrier.
- **PMT path is the tight one:** 5-7 ns pulses → use a fast translator/comparator,
  a short controlled-impedance trace, and a clock-capable FPGA pin. This is the
  one signal where pin choice actually matters for performance.
- **Bank VCCIO:** the pulser 3.3V I/O must land in expansion banks set to 3.3V —
  confirm from the User's Guide which JP2/JP3 pins are on 3.3V-capable banks (not
  the 1.5V DDR3 banks). Group all TTL on the same bank(s) where possible.
- **Grounds / returns:** bring plenty of the connector's GND pins through to the
  carrier next to the fast lines (PMT, clock).

## 4. To finish this (what I need)

Give me the **XEM7305 expansion pinout table** (JP2/JP3 pin ↔ FPGA pin ↔ bank),
and I'll:
1. fill the "FPGA pin / Conn pin / bank" columns above,
2. generate the matching `constraints/xem7305.xdc` additions (`PACKAGE_PIN` +
   `IOSTANDARD LVCMOS33`) for `logic_out[31:0]` / `pmt_input` / `logic_in[3:0]` /
   `aux_clk_in`,
3. add those ports to `photon.vhd` and wire `logic_out <= master_logic`,
   `pmt_in_muxed <= pmt_input when …`, `logic_in(0) → line trigger`,
so the "breakout board" firmware step and the PCB net list stay in sync.
