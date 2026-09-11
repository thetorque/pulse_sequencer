#!/usr/bin/env python3
"""
pmt_timetag_demo.py -- M4c time-resolved timetag readout via the pulser3 Driver.

Drives the on-FPGA synthetic PMT source, records photon timestamps for a
detection window, and verifies the timestamps are evenly spaced -- the same
self-check as the ad-hoc test/pmt_timetag_bringup.py but through
Driver.pmt_record_* / pmt_read_timetags (Hz in, timestamps out). Needs an
m4b+ bitstream (the timetagger datapath).

    python -m pulser3.pmt_timetag_demo <photon.bit> [--rate-hz R] [--tags N]

The source runs on clk_100 (period P cycles); the timetagger on clk_200 (5 ns/
tick), so consecutive timestamps differ by exactly 2*P ticks.
"""
import argparse
import sys
import time

from . import Driver


def main(argv=None):
    ap = argparse.ArgumentParser(description="pulser3 PMT timetag demo")
    ap.add_argument("bit", help="path to photon .bit (m4b+ bitstream)")
    ap.add_argument("--rate-hz", type=float, default=5e5, help="synthetic source rate (default 500 kHz)")
    ap.add_argument("--tags", type=int, default=64, help="timestamps to collect (default 64)")
    args = ap.parse_args(argv)

    d = Driver()
    print(f"Connecting and configuring {args.bit} ...")
    d.connect(args.bit)

    period = d.rate_to_period(args.rate_hz)     # clk_100 cycles
    expect_diff = 2 * period                     # clk_200 ticks between timestamps
    print(f"\n--- PMT timetagger: {args.rate_hz:g} Hz source -> period={period} "
          f"clk_100 cycles -> expect {expect_diff}-tick (5 ns) spacing "
          f"= {expect_diff * 5} ns ---")

    # clean start: stop, clear fifo_photon, reset the counter/source/time base
    d.pmt_record_stop()
    d.pmt_timetag_reset()
    d.reset()

    # open the detection window
    d.pmt_record_start(synthetic=True, period_cycles=period)

    t0 = time.time()
    while d.pmt_timetags_available() < args.tags:
        if time.time() - t0 > 5.0:
            sys.exit(f"  TIMEOUT: only {d.pmt_timetags_available()} timestamps after 5 s "
                     f"(timetagger not recording)")
        time.sleep(0.005)

    d.pmt_record_stop()
    tags = d.pmt_read_timetags()
    print(f"  recorded {len(tags)} timestamps; first/last = {tags[0]} / {tags[-1]} "
          f"({d.ticks_to_seconds(tags[-1] - tags[0]) * 1e3:.3f} ms span)")

    diffs = [b - a for a, b in zip(tags, tags[1:])]
    errors = sum(1 for x in diffs if x != expect_diff)
    if errors == 0 and len(diffs) >= 1:
        print(f"  RESULT: PASS -- every spacing == {expect_diff} ticks "
              f"({expect_diff * 5} ns)")
        return 0
    bad = [x for x in diffs if x != expect_diff][:8]
    print(f"  RESULT: FAIL -- {errors} spacing(s) off expected {expect_diff}; "
          f"examples: {bad}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
