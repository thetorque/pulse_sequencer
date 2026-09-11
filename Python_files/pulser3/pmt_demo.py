#!/usr/bin/env python3
"""
pmt_demo.py -- M3 normal-mode PMT readout via the pulser3 Driver API.

Drives the on-FPGA synthetic PMT source at a known rate and verifies the
per-window counts, the same self-check as the ad-hoc test/pmt_bringup.py but
through Driver.pmt_* (seconds/Hz in, counts out) instead of raw ok calls --
proving the ported host API. Needs an m2+ bitstream (the PMT datapath).

    python -m pulser3.pmt_demo <photon.bit> [--rate-hz R] [--gate-ms G] [--windows N]

With a deterministic source, every steady window must read exactly
gate_cycles // period_cycles counts (the first window reads one low -- the
reset/sync startup transient -- and is skipped).
"""
import argparse
import sys
import time

from . import Driver


def main(argv=None):
    ap = argparse.ArgumentParser(description="pulser3 PMT normal-count demo")
    ap.add_argument("bit", help="path to photon .bit (m2+ bitstream)")
    ap.add_argument("--rate-hz", type=float, default=1e6, help="synthetic source rate (default 1 MHz)")
    ap.add_argument("--gate-ms", type=float, default=1.0, help="collection window (default 1 ms)")
    ap.add_argument("--windows", type=int, default=12, help="windows to collect (default 12)")
    args = ap.parse_args(argv)

    d = Driver()
    print(f"Connecting and configuring {args.bit} ...")
    d.connect(args.bit)

    period = d.rate_to_period(args.rate_hz)
    gate = d.seconds_to_cycles(args.gate_ms / 1000.0)
    expect = gate // period
    print(f"\n--- PMT normal-count: {args.rate_hz:g} Hz source, {args.gate_ms:g} ms gate "
          f"-> period={period}, gate={gate} cycles -> expect {expect} counts/window ---")

    # clean start: stop, clear the FIFO, reset the counter/source
    d.pmt_stop()
    d.pmt_reset_fifo()
    d.reset()
    d.pmt_configure(gate, period)
    d.pmt_start(synthetic=True)

    t0 = time.time()
    while d.pmt_available() < args.windows:
        if time.time() - t0 > 5.0:
            sys.exit(f"  TIMEOUT: only {d.pmt_available()} windows after 5 s "
                     f"(counts not reaching normal_pmt_fifo)")
        time.sleep(0.005)

    d.pmt_stop()
    counts = d.pmt_read_counts()
    print(f"  collected {len(counts)} windows: {counts}")

    errors = sum(1 for i, c in enumerate(counts) if i >= 1 and c != expect)
    if errors == 0 and len(counts) >= 2:
        print(f"  RESULT: PASS -- every steady window == {expect} counts")
        return 0
    print(f"  RESULT: FAIL -- {errors} window(s) off expected {expect}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
