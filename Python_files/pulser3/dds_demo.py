"""
dds_demo.py -- hardware bring-up of the Phase-4 DDS bus from the host (roadmap 3.3 / 3.4).

Runs on the bench PC (the XEM7305 is USB-attached there) with the Phase-4 photon
bitstream. The DDS board(s) must run dds_top (DDS_ECP5_2026_10_19). Every frame is
broadcast, so the boards' address straps don't matter.

    python -m pulser3.dds_demo <photon.bit> --trigger          # 3.3: host-stepped
    python -m pulser3.dds_demo <photon.bit> --sequence         # 3.4: TTL-18-stepped
    python -m pulser3.dds_demo --dump                          # print the frames, no HW

Table (both modes, --freqs to change): 60 / 110 / 160 / 210 MHz at VGA 0xB40 (~0 dBm @ 50 MHz on board 8),
then 210 MHz with RF OFF. Deliberately NOT bp_proto's 50/100/150/200, so a pass
can't be leftover state from the old test sender.

--trigger : writes the 5 rows, RESET via TriggerIn 0x40 bit 7 (RAMRESET line) AND a
            RESET frame (works even if RAMRESET isn't wired), then a STEP trigger
            (bit 6, STEPNEXT line) every --dwell seconds, cycling forever.
--sequence: fills all 8192 rows with the 5-row pattern repeated, so the table cycles
            without needing RAMRESET (c17/c18 not yet wired on the bench coupler),
            RESET frame once, then runs a TTL sequence in an infinite loop: an
            AdvanceDDS (ch 18) pulse every --dwell seconds, 5 per loop, plus a
            marker pulse on 'ttl_0' at each step (scope ttl_0 vs the RF output to
            see the step latency). Ctrl-C stops.
"""
import argparse
import sys
import time

from . import dds as D

DEFAULT_FREQS_MHZ = (60.0, 110.0, 160.0, 210.0)
PATTERN, LABELS = [], []


def set_table(freqs_mhz):
    """The rows: each frequency with RF on, then the last one with RF OFF."""
    PATTERN[:] = [D.Row(f * 1e6, 0.0, 0xB40, True) for f in freqs_mhz] + \
                 [D.Row(freqs_mhz[-1] * 1e6, 0.0, 0xB40, False)]
    LABELS[:] = [f"{f:g} MHz" for f in freqs_mhz] + [f"{freqs_mhz[-1]:g} MHz RF OFF"]


set_table(DEFAULT_FREQS_MHZ)


def dump():
    for name, frames in (("trigger table", [D.write_rows(D.BROADCAST, 0, PATTERN), D.reset()]),
                         ("RESET frame", [D.reset()])):
        s = D.pack(frames)
        print(f"{name}: {len(s)} bytes")
        for i in range(0, len(s), 16):
            print("   ", s[i:i + 16].hex(" "))


def run_trigger(drv, dwell):
    x = drv.xem
    D.clear_pipe(x)
    D.send(x, [D.write_rows(D.BROADCAST, 0, PATTERN)])
    D.trigger_reset(x)
    D.send(x, [D.reset()])
    k = 0
    print(f"row 0: {LABELS[0]}")
    try:
        while True:
            time.sleep(dwell)
            if k == len(PATTERN) - 1:
                D.trigger_reset(x)               # RAMRESET line (if wired) ...
                D.send(x, [D.reset()])           # ... and the frame, which always works
                k = 0
            else:
                D.trigger_step(x)
                k += 1
            print(f"row {k}: {LABELS[k]}")
    except KeyboardInterrupt:
        print("\nstopped")


def run_sequence(drv, dwell):
    from . import hwconfig
    x = drv.xem
    D.clear_pipe(x)
    table = [PATTERN[i % len(PATTERN)] for i in range(D.N_ROWS)]
    t0 = time.time()
    n = D.send(x, D.program_board(D.BROADCAST, table))
    print(f"wrote 8192 rows ({n} bytes) in {time.time() - t0:.2f} s")
    D.send(x, [D.reset()])

    seq = hwconfig.new_sequence()
    for i in range(len(PATTERN)):
        t = (i + 1) * dwell
        seq.add_pulse('AdvanceDDS', t, 1e-6)     # STEPNEXT
        seq.add_pulse('ttl_0', t, 1e-6)          # scope marker
    seq.extend_length(len(PATTERN) * dwell + 0.1)
    drv.load_program(seq.to_lines(), verify=True)
    print(f"sequence: {len(PATTERN)} AdvanceDDS steps, {dwell} s apart; infinite loop")
    drv.start_infinite()
    try:
        last = -1
        while True:
            c = drv.seq_count()
            if c != last:
                print(f"  loop {c}")
                last = c
            time.sleep(0.2)
    except KeyboardInterrupt:
        drv.stop()
        print("\nstopped")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase-4 DDS bus demo")
    ap.add_argument("bit", nargs="?", help="Phase-4 photon .bit")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--trigger", action="store_true")
    g.add_argument("--sequence", action="store_true")
    g.add_argument("--dump", action="store_true")
    ap.add_argument("--dwell", type=float, default=5.0, help="seconds per row (default 5)")
    ap.add_argument("--freqs", default=",".join(f"{f:g}" for f in DEFAULT_FREQS_MHZ),
                    help="comma-separated MHz, RF on; the last is repeated with RF off "
                         "(default %(default)s)")
    a = ap.parse_args(argv)
    set_table([float(f) for f in a.freqs.split(",")])
    print("table:", " -> ".join(LABELS))
    if a.dump:
        dump()
        return 0
    if not a.bit:
        ap.error("bit path required")
    from . import Driver
    drv = Driver()
    print(f"configuring {a.bit} ...")
    drv.connect(a.bit)
    (run_trigger if a.trigger else run_sequence)(drv, a.dwell)
    return 0


if __name__ == "__main__":
    sys.exit(main())
