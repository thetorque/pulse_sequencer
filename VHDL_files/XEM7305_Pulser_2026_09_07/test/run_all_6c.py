#!/usr/bin/env python3
"""
run_all_6c.py -- run the full Phase 6c regression suite against one bitstream
and print a single PASS/FAIL summary.

    python run_all_6c.py <photon.bit> [memtest_mib]

Each test runs as its own subprocess (each reconfigures the FPGA, so they are
independent and order-insensitive) with output streamed live. The suite:

  1. smoke_test          -- bring-up sanity: LEDs, clocks, MMCM lock, MIG
                            calibration, FIFOs, a minimal sequencer run.
                            *** INTERACTIVE: pauses at the LED checks -- press
                            Enter (and glance at the LEDs) to continue. ***
  2. ddr3 memtest        -- legacy DDR3 write/read integrity, whole-array
                            write-then-verify (the cold-start --sacrifice-beat0
                            workaround). Default 128 MiB (~13 min); pass a
                            smaller size as the 2nd arg for a quicker pass.
  3. loop_test_demo      -- legacy pulser_ram finite + infinite loop path.
  4. bringup (default)   -- Phase 6c: 12-state waveform, bit-exact, seq_done.
  5. bringup --long      -- Phase 6c: sustained streaming across the cold-start
                            boundary; checks seq_done, drop flag 0, exact
                            line_count.
  6. bringup --loops 5   -- Phase 6c: finite loop (seq_count==5, line_count).
  7. bringup --loop      -- Phase 6c: infinite loop / restart repeats.

Exits 0 only if every test passed; non-zero (and lists the failures) otherwise.
smoke_test's interactivity means this is a supervised run, not a cron job.
"""
import os
import subprocess
import sys
import time


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python run_all_6c.py <photon.bit> [memtest_mib]")
    bit = sys.argv[1]
    mib = sys.argv[2] if len(sys.argv) > 2 else "128"
    here = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable

    suite = [
        ("smoke_test (bring-up -- INTERACTIVE, press Enter at LED checks)",
         ["smoke_test.py", bit]),
        (f"DDR3 memtest {mib} MiB (legacy write/read integrity)",
         ["ddr3_roundtrip_demo.py", bit, "memtest", mib, "--sacrifice-beat0"]),
        ("legacy pulser_ram loop path (loop_test_demo)",
         ["loop_test_demo.py", bit]),
        ("Phase 6c DDR3 sequencer -- 12-state waveform",
         ["ddr3_sequencer_bringup.py", bit]),
        ("Phase 6c DDR3 sequencer -- sustained streaming (--long)",
         ["ddr3_sequencer_bringup.py", bit, "--long"]),
        ("Phase 6c DDR3 sequencer -- finite loop (--loops 5)",
         ["ddr3_sequencer_bringup.py", bit, "--loops", "5"]),
        ("Phase 6c DDR3 sequencer -- infinite loop (--loop)",
         ["ddr3_sequencer_bringup.py", bit, "--loop"]),
    ]

    results = []
    t_start = time.time()
    for name, cmd in suite:
        print("\n" + "=" * 74)
        print(f">>> {name}")
        print("=" * 74, flush=True)
        t0 = time.time()
        rc = subprocess.call([py, os.path.join(here, cmd[0])] + cmd[1:])
        results.append((name, rc, time.time() - t0))

    print("\n" + "=" * 74)
    print("PHASE 6c REGRESSION SUMMARY")
    print("=" * 74)
    npass = 0
    for name, rc, dt in results:
        tag = "PASS" if rc == 0 else f"FAIL (exit {rc})"
        npass += (rc == 0)
        print(f"  [{tag:14}] {dt:6.0f}s  {name}")
    total = len(results)
    print(f"\n  {npass}/{total} passed in {time.time() - t_start:.0f}s total.")
    if npass == total:
        print("  Phase 6c CLEAR: legacy regression + DDR3 sequencer "
              "(waveform, streaming, loops) all green.")
    else:
        print("  NOT clear -- see the FAIL rows above; scroll up for that "
              "test's output.")
    sys.exit(0 if npass == total else 1)


if __name__ == "__main__":
    main()
