"""
dds_soak.py -- roadmap 1.3: long DDS stepping soak with an exact end-of-run check.

    python -m pulser3.dds_soak <photon.bit> [--hours 2] [--spacing-us 5] [--steps 500]

Needs the master FPGA board on the PC (stop the Pulser server first: one program per
FPGA). Every frame is broadcast, so the board's address doesn't matter.

How it proves "no step lost or added":
  * all 8192 table rows are DIFFERENT frequencies: row k = 50 MHz + k kHz (~-10 dBm,
    RF on), so the row the board ends on is readable on the frequency counter;
  * a TTL sequence fires --steps AdvanceDDS pulses --spacing-us apart (5 us = the
    contract minimum, so it also stresses the preload) and runs in blocks of
    start_number(65535) repetitions, with NO resets in between -- the board's row
    pointer counts every step and wraps at 8192;
  * at the end the board sits on row (total steps mod 8192), and the script prints
    the frequency the counter must show. One lost/extra step anywhere -> a different
    reading. The board's red D3 (frame error) / D4 (step overrun) must stay dark --
    they latch, and the script sends CLEAR_STATUS before starting.

Stop early (cleanly, at the next block boundary): create the file STOP_SOAK in the
current directory. Ctrl-C stops at once, but then the expected row is unknown.
"""
import argparse
import os
import sys
import time

from . import dds as D
from . import hwconfig

BASE_HZ = 50e6
STEP_HZ = 1e3
BLOCK = 65535                      # start_number maximum
STOP_FILE = "STOP_SOAK"


def table():
    return [D.row_dbm(BASE_HZ + k * STEP_HZ, -10.0) for k in range(D.N_ROWS)]


def expected_hz(total_steps):
    return D.Row(BASE_HZ + (total_steps % D.N_ROWS) * STEP_HZ).exact_hz


def main(argv=None):
    ap = argparse.ArgumentParser(description="DDS stepping soak (roadmap 1.3)")
    ap.add_argument("bit")
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--spacing-us", type=float, default=5.0)
    ap.add_argument("--steps", type=int, default=500, help="AdvanceDDS pulses per loop (<= 500)")
    a = ap.parse_args(argv)
    if a.spacing_us < 5.0:
        ap.error("spacing below the 5 us contract minimum")
    if not 1 <= a.steps <= 500:
        ap.error("steps per loop must be 1..500 (TTL switch budget)")

    from . import Driver
    drv = Driver()
    print(f"configuring {a.bit} ...", flush=True)
    x = drv.connect(a.bit)

    # table + clean status, board on row 0
    D.clear_pipe(x)
    frames = [D.clear_status()] + D.program_board(D.BROADCAST, table()) + [D.reset()]
    n = D.send(x, frames)                 # returns once the table is on the bus
    print(f"table: 8192 rows, 50.000 .. {(BASE_HZ + 8191 * STEP_HZ) / 1e6:.3f} MHz "
          f"({n} bytes); board on row 0 = 50.000000 MHz", flush=True)

    # the stepping sequence
    seq = hwconfig.new_sequence()
    sp = a.spacing_us * 1e-6
    for i in range(a.steps):
        seq.add_pulse('AdvanceDDS', (i + 1) * sp, 120e-9)
    seq.extend_length((a.steps + 1) * sp)
    # verify=False: the read-back uses the DDR3 read path, which can hit the known
    # cold-start mis-address (roadmap 3.2); the write is fine and every block is
    # checked below (done + loop count + streamer overflow) -- same as the server.
    drv.load_program(seq.to_lines(), verify=False)
    per_block = BLOCK * a.steps
    print(f"sequence: {a.steps} steps x {a.spacing_us:g} us per loop; "
          f"block = {BLOCK} loops = {per_block:,} steps", flush=True)

    total, blocks, t0 = 0, 0, time.time()
    deadline = t0 + a.hours * 3600
    try:
        while time.time() < deadline and not os.path.exists(STOP_FILE):
            tb = time.time()
            drv.start_number(BLOCK)
            if not drv.wait_done(timeout=BLOCK * (a.steps + 2) * sp * 3 + 60):
                print("ERROR: block did not finish -- stopping", flush=True)
                break
            ovf = drv.overflow()
            done = drv.seq_count()
            blocks += 1
            total += per_block
            print(f"block {blocks}: {time.time() - tb:6.1f} s, loops={done}, "
                  f"overflow={int(ovf)}, total steps={total:,}, "
                  f"board should be on row {total % D.N_ROWS} = "
                  f"{expected_hz(total) / 1e6:.6f} MHz  "
                  f"[{(time.time() - t0) / 3600:.2f} h]", flush=True)
            if ovf or done != BLOCK:
                print("WARNING: sequencer overflow / loop count mismatch in this block", flush=True)
    except KeyboardInterrupt:
        drv.stop()
        print("\ninterrupted mid-block: the expected row is unknown", flush=True)
        return 1
    drv.stop()
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    print(f"\nSOAK DONE: {blocks} blocks, {total:,} steps in "
          f"{(time.time() - t0) / 3600:.2f} h", flush=True)
    print(f"CHECK: the counter must read {expected_hz(total) / 1e6:.6f} MHz "
          f"(row {total % D.N_ROWS}); DDS board D3 and D4 must NOT be red.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
