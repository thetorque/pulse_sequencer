#!/usr/bin/env python3
"""
run_demo.py -- M1 end-to-end proof for the pulser3 driver.

Reproduces the 12-state bring-up waveform (the same STEPS as
ddr3_sequencer_bringup.py) but drives it entirely through the pulser3.Driver
API instead of raw ok calls -- so a green run here proves the ported driver
connects, loads DDR3, runs, and reads status correctly against real hardware.

    python -m pulser3.run_demo <photon.bit> [--infinite | --loops N]

Watch WireOut 0x2B (master_logic) on the LEDs advance through the pattern.
"""
import argparse
import sys
import time

from . import Driver, line, TICKS_PER_SEC

# (absolute time in seconds, channel bitmask) -- first line applied immediately
# (its time ignored), later times strictly increasing; final 0x000 turns all
# off, then the terminator ends the run. Kept in the low 12 bits so master_logic
# reads back cleanly on WireOut 0x2B.
STEPS = [
    (0.0, 0x001), (0.6, 0x003), (1.1, 0x007), (1.5, 0x00F),
    (2.2, 0x03F), (2.7, 0x555), (3.3, 0xAAA), (3.8, 0xFFF),
    (4.4, 0x111), (5.0, 0x888), (5.7, 0x249), (6.5, 0x000),
]


def build_lines():
    lines = [line(int(t * TICKS_PER_SEC), ch) for (t, ch) in STEPS]
    expected = [ch for (_, ch) in STEPS if ch != 0]
    return lines, expected


def main(argv=None):
    ap = argparse.ArgumentParser(description="pulser3 driver M1 demo")
    ap.add_argument("bit", help="path to photon .bit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--infinite", action="store_true", help="loop forever")
    g.add_argument("--loops", type=int, metavar="N", help="loop N times")
    args = ap.parse_args(argv)

    lines, expected = build_lines()
    n_real = len(lines)   # states incl. the final all-off, before padding

    d = Driver()
    print(f"Connecting and configuring {args.bit} ...")
    d.connect(args.bit)

    prog = d.load_program(lines, verify=True)
    print(f"Loaded {len(prog)} lines to DDR3 (verify OK); "
          f"{n_real} program states + terminator/pad.")

    if args.infinite:
        print("Starting INFINITE loop -- watch the LEDs; Ctrl-C to stop.")
        d.start_infinite()
        try:
            last = -1
            while True:
                c = d.seq_count()
                if c != last:
                    print(f"  iterations completed: {c}   logic=0x{d.logic_out():03X}")
                    last = c
                time.sleep(0.2)
        except KeyboardInterrupt:
            d.stop()
            print(f"\nStopped after {d.seq_count()} iterations.")
        return 0

    if args.loops:
        print(f"Starting {args.loops} loops ...")
        d.start_number(args.loops)
        ok = d.wait_done(timeout=90.0)
        cnt, lc, ovf = d.seq_count(), d.line_count(), d.overflow()
        # line_count integrity: each pass pops (states + terminator) padded lines
        expect_lc = args.loops * len(prog)
        good = ok and cnt == args.loops and not ovf
        print(f"  done={ok}  seq_count={cnt}/{args.loops}  "
              f"line_count={lc} (expect {expect_lc})  drop={ovf}")
        print("  RESULT:", "PASS" if good else "FAIL")
        return 0 if good else 1

    # single run
    print("Starting SINGLE run ...")
    d.start_single()
    ok = d.wait_done(timeout=30.0)
    lc, ovf, logic = d.line_count(), d.overflow(), d.logic_out()
    # one pass pops every padded line exactly once
    good = ok and not ovf and lc == len(prog) and logic == 0x000
    print(f"  done={ok}  line_count={lc} (expect {len(prog)})  "
          f"drop={ovf}  final_logic=0x{logic:03X} (expect 0x000)")
    print(f"  program channel order was: {[f'0x{c:03X}' for c in expected]}")
    print("  RESULT:", "PASS" if good else "FAIL")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
