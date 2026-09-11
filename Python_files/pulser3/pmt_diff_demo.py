#!/usr/bin/env python3
"""
pmt_diff_demo.py -- M4d differential (sequence-gated) PMT counting via pulser3.

The first PMT x sequencer end-to-end test. Builds a pulse program that gates the
detection windows itself -- channel 16 (DiffCountTrigger) pulsed once per window,
channel 0 (866) held at a chosen state -- runs it on the DDR3 sequencer while the
synthetic PMT source feeds photons, then reads back the per-window counts and the
866 status tag from normal_pmt_fifo (0xA1).

    python -m pulser3.pmt_diff_demo <photon.bit> [--windows N] [--dwell-us D]
                                    [--rate-hz R] [--repump-off]

With a deterministic source, each window collects (dwell x rate) photons, and
each count word's status must match the programmed 866 state. Needs an m4d
bitstream. Uses the DDR3 program store, so this doubles as a sequencer+PMT
integration check.
"""
import argparse
import sys

from . import Driver, Sequence
from . import wiremap as W


def build_program(n_windows, dwell_s, trig_width_s, repump_on):
    """A program that pulses ch16 once per window (rising edge = window close)
    and holds ch0 (866) at repump_on for the whole run. Returns the line list."""
    seq = Sequence(channel_total=32)
    total = (n_windows + 1) * dwell_s
    if repump_on:
        seq.add_pulse(W.CH_866, 0.0, total)                 # 866 ON the whole run
    for k in range(1, n_windows + 1):
        seq.add_pulse(W.CH_DIFF_TRIGGER, k * dwell_s, trig_width_s)  # window boundary k
    return seq.to_lines()


def main(argv=None):
    ap = argparse.ArgumentParser(description="pulser3 differential PMT demo")
    ap.add_argument("bit", help="path to photon .bit (m4d bitstream)")
    ap.add_argument("--windows", type=int, default=8, help="detection windows (default 8)")
    ap.add_argument("--dwell-us", type=float, default=100.0, help="window length us (default 100)")
    ap.add_argument("--rate-hz", type=float, default=1e6, help="synthetic source rate (default 1 MHz)")
    ap.add_argument("--repump-off", action="store_true", help="hold 866 OFF (expect status OFF)")
    args = ap.parse_args(argv)

    dwell_s = args.dwell_us * 1e-6
    repump_on = not args.repump_off
    period = Driver.rate_to_period(args.rate_hz)
    expect = round(dwell_s * args.rate_hz)
    lines = build_program(args.windows, dwell_s, dwell_s * 0.1, repump_on)

    d = Driver()
    print(f"Connecting and configuring {args.bit} ...")
    d.connect(args.bit)
    print(f"\n--- Differential PMT: {args.windows} windows x {args.dwell_us:g} us, "
          f"{args.rate_hz:g} Hz source (866 {'ON' if repump_on else 'OFF'}) "
          f"-> expect ~{expect} counts/window, status "
          f"{'ON' if repump_on else 'OFF'} ---")

    d.load_program(lines, verify=True)
    d.pmt_reset_fifo()
    d.pmt_diff_start(synthetic=True, period_cycles=period)   # diff mode + source
    d.start_single()                                          # run the gating program
    if not d.wait_done(timeout=30.0):
        d.pmt_diff_stop()
        sys.exit("  sequence did not finish (seq_done never asserted)")
    d.pmt_diff_stop()

    counts = d.pmt_read_diff_counts()
    print(f"  read {len(counts)} windows: "
          + ", ".join(f"{c}{'on' if on else 'OFF'}" for c, on in counts))

    errors = 0
    for i, (c, on) in enumerate(counts):
        if on != repump_on:
            errors += 1
            print(f"    window {i}: status {'ON' if on else 'OFF'} "
                  f"(expected {'ON' if repump_on else 'OFF'})")
        if abs(c - expect) > 2:
            errors += 1
            print(f"    window {i}: count {c} (expected ~{expect})")
    good = errors == 0 and len(counts) >= args.windows - 1
    print("  RESULT:", "PASS" if good else "FAIL",
          f"-- {len(counts)} windows, status all "
          f"{'ON' if repump_on else 'OFF'}, counts ~{expect}"
          if good else f"-- {errors} problem(s)")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
