#!/usr/bin/env python3
"""
ddr3_sequencer_bringup.py -- Phase 6c first-light bring-up for the DDR3
sequencer path (ep00wire(5)=1).

This is the counterpart to ddr3_roundtrip_demo.py. Instead of just
round-tripping DDR3, it exercises the WHOLE Phase 6c chain on hardware:

    host writes a pulse program into DDR3  (write-assembler path)
        -> ddr3_line_streamer reads it back (ui_clk)
            -> line FIFO (fifo_128x4)
                -> pulse_sequencer pops 64-bit lines (clk_100)
                    -> master_logic / logic_out / led_ext

It writes a deliberately SLOW program -- state changes one second apart --
so you can watch master_logic (WireOut 0x2B) advance in real time and see
led_ext[0..3] walk, exactly like loop_test_demo. A --fast flag instead
loads the sim's tight {t=3,8,10}-tick demo for a scope / logic analyzer.

Pulse-line format (see memory/pulse-sequence-ram-format): a 64-bit line is
  channel = bits[31:0], time = bits[61:32] (ABSOLUTE cumulative tick of the
  state change), terminator = the all-zero line. A line's channel is held
  until the NEXT line's time. tick = 4*clk_100 = 40 ns => 25e6 ticks / s.

Control bits (ep00wire), status (WireOut), reset (TriggerIn 0x40 bit 0):
  bit1 infinite loop, bit2 start, bit3 line-trigger en, bit4 write/read
  mode (0=write), bit5 DDR3-sequencer mode. 0x2B = logic_out (= master_logic
  when the ep02/ep03 override mux is off). 0x2C bit16 = seq_done, [15:0] =
  seq_count.

Why no --sacrifice-beat0 here: the program lives at DDR3 address 0, inside
the low 32 KiB that is structurally immune to the cold-start row mis-address
(app_addr bit 14 is 0 there and the fault only ever CLEARS bit 14) -- see
memory/ddr3-read-adapter-design. So the streamer's initial prime read of the
program is safe without a sacrificial dummy.

Usage:
    python ddr3_sequencer_bringup.py <path-to-photon.bit> [--fast]

Requires the Opal Kelly `ok` FrontPanel Python module and, alongside it,
ddr3_roundtrip_demo.py (this script imports its proven connect / write /
read / reset helpers rather than re-implementing the MIG handshakes).
"""

import sys
import time

import ok
from ddr3_roundtrip_demo import connect, reset_ddr3, write_words, read_words

# ---- ep00wire control bits -------------------------------------------------
INFINITE_BIT = 1 << 1   # ep00wire(1): pulser_infinite_loop
START_BIT    = 1 << 2   # ep00wire(2): pulser_start_bit
LINETRIG_BIT = 1 << 3   # ep00wire(3): line-trigger enable
READMODE_BIT = 1 << 4   # ep00wire(4): 0 = write mode, 1 = read mode
SEQMODE_BIT  = 1 << 5   # ep00wire(5): 1 = DDR3 sequencer, 0 = legacy pulser_ram

# ---- status / reset --------------------------------------------------------
LOGIC_WIRE   = 0x2B     # ep2Bwire = logic_out (= master_logic, overrides off)
SEQ_WIRE     = 0x2C     # ep2Cwire: bit16 = seq_done, bits[15:0] = seq_count
SEQ_DONE_BIT = 1 << 16
OVERFLOW_BIT = 1 << 17   # ep2Cwire bit 17: streamer sticky dropped-beat flag
LINE_COUNT_WIRE = 0x35   # ep35wire: lines the sequencer popped this run (integrity)
RESET_TRIG_ADDR = 0x40  # TriggerIn 0x40
RESET_TRIG_BIT  = 0     # bit 0: pulser_counter_reset

TICKS_PER_SEC = 25_000_000   # tick = 40 ns

# streamer PRIME_BEATS=8 -> 16 lines primed before it reports ready; pad the
# program to that so the whole primed window is program + terminators, never
# stale DDR3 content.
PRIME_LINES = 16


def line(time_ticks, channel):
    """Pack one 64-bit pulse line: time in bits[61:32], channel in [31:0]."""
    return ((time_ticks & 0x3FFFFFFF) << 32) | (channel & 0xFFFFFFFF)


# Program steps as (absolute time, channel). Semantics (see pulse_sequencer):
# the FIRST step's channel is applied IMMEDIATELY (its time is ignored); every
# later step's channel is applied when the free-running tick count reaches its
# absolute time, so times MUST strictly increase. A final channel-0 step turns
# everything off, then the all-zero terminator ends the run.
#
# Channels are kept within the low 12 bits (the explicitly override-muxed
# channels 0-11) so master_logic reads back cleanly on WireOut 0x2B; low 6 bits
# also drive led_ext. Dwells are deliberately NON-uniform to stress the
# absolute-time engine, and the patterns are distinct (walking fill, alternating
# 0x555/0xAAA, nibble patterns, all-on 0xFFF) so any residual ordering or bit
# mapping error is obvious.
STEPS_SLOW = [
    # (t seconds, channel)
    (0.0, 0x001),   # applied immediately (time ignored)
    (0.6, 0x003),
    (1.1, 0x007),
    (1.5, 0x00F),
    (2.2, 0x03F),   # low 6 all on -> all LEDs on
    (2.7, 0x555),   # alternating
    (3.3, 0xAAA),   # alternating (complement)
    (3.8, 0xFFF),   # all 12 on
    (4.6, 0xF0F),
    (5.1, 0x0F0),
    (5.9, 0x111),
    (6.5, 0x888),
    (7.2, 0x000),   # all off (real line, not terminator)
]

# Fast (scope / logic-analyzer) variant: tight absolute ticks, more edges.
STEPS_FAST = [
    (0,  0x01), (3,  0x02), (6,  0x04), (9,  0x08),
    (12, 0x10), (15, 0x20), (18, 0x3F), (21, 0x2A),
    (24, 0x15), (27, 0x00),
]


def build_program(fast):
    """The bring-up program as an ordered list of 64-bit lines, terminator
    included, padded to PRIME_LINES with terminators (even count). Returns
    (lines, expected) where expected is the nonzero channels in order."""
    steps = STEPS_FAST if fast else STEPS_SLOW
    scale = 1 if fast else TICKS_PER_SEC
    lines = [line(int(t * scale), ch) for (t, ch) in steps]
    lines.append(0x0)                          # terminator -> seq_done
    while len(lines) < PRIME_LINES or len(lines) % 2 != 0:
        lines.append(0x0)                      # pad with terminators (even count)
    expected = [ch for (_, ch) in steps if ch != 0]
    return lines, expected


# The DDR3 address the streamer reaches leaves the cold-start-immune low 32 KiB
# (app_addr < 0x4000) after this many program lines: 0x4000 / ADDR_INC(8) beats
# x 2 lines/beat.
IMMUNE_LINES = (0x4000 // 8) * 2   # = 4096


def build_long_program(n_lines, dwell_ticks):
    """A long ramp program: n_lines states of dwell_ticks each, channel = line
    index in the low 12 bits so a hang location is identifiable. Streaming it
    forces the streamer past the cold-start-immune boundary (IMMUNE_LINES) and,
    with per-line dwells that keep the FIFO full, forces the controller to idle
    between refills -- exercising the keep-warm heartbeat. Returns
    (lines, dwell_ticks) with dwell_ticks possibly clamped to fit the 30-bit
    absolute-time field."""
    max_dwell = (2 ** 30 - 1) // (n_lines + 1)
    if dwell_ticks > max_dwell:
        dwell_ticks = max_dwell
    # channel = 1..4095 (NEVER 0) so master_logic==0 means ONLY done/terminator,
    # and a stall (which holds the last applied channel) freezes at a nonzero
    # value that names the exact line: i == (channel-1) mod 4095.
    lines = [line((i + 1) * dwell_ticks, (i % 0xFFF) + 1) for i in range(n_lines)]
    lines.append(0x0)                          # terminator -> seq_done
    while len(lines) < PRIME_LINES or len(lines) % 2 != 0:
        lines.append(0x0)
    return lines, dwell_ticks


def set_ep00(xem, value):
    """Drive ep00wire to an absolute value (all bits) and commit."""
    xem.SetWireInValue(0x00, value, 0xFFFFFFFF)
    xem.UpdateWireIns()


def pulse_reset(xem):
    xem.ActivateTriggerIn(RESET_TRIG_ADDR, RESET_TRIG_BIT)  # pulser_counter_reset


def write_and_verify(xem, prog, verify_words):
    """Write prog to DDR3 @ 0, then read back the first verify_words words
    (kept within the cold-start-immune low 32 KiB) to confirm the write path
    landed before we trust the streamer. Aborts on mismatch."""
    reset_ddr3(xem)
    write_words(xem, prog)
    print(f"  wrote {len(prog)} lines to DDR3 @ address 0")
    reset_ddr3(xem)
    got = read_words(xem, verify_words)
    if got == prog[:verify_words]:
        scope = "all" if verify_words == len(prog) else f"first {verify_words}"
        print(f"  readback verify ({scope} words): DDR3 matches the program  [OK]")
        return
    print("  readback verify: MISMATCH -- the WRITE path is wrong, not the")
    print("  streamer. First differences (index: wrote -> read):")
    shown = 0
    for i, (w, r) in enumerate(zip(prog[:verify_words], got)):
        if w != r:
            print(f"    [{i}] {w:#018x} -> {r:#018x}")
            shown += 1
            if shown >= 6:
                break
    sys.exit("aborting: fix the write path before bringing up the stream")


def start_sequencer(xem, infinite=False, loop_limit=0):
    """Enter DDR3 sequencer mode and start. Leaves write mode (bit4=0): while
    streaming, the mux hands MIG's command channel to the streamer and the
    write path sits idle. loop_limit (ep05, 16-bit) caps infinite loops: 0 =
    unlimited, N = stop after N iterations."""
    xem.SetWireInValue(0x05, loop_limit & 0xFFFF, 0xFFFFFFFF)  # ep05: loop_limit
    xem.UpdateWireIns()
    base = SEQMODE_BIT | (INFINITE_BIT if infinite else 0)
    set_ep00(xem, base)              # seq mode (+ infinite), start still off
    pulse_reset(xem)                 # reset the sequencer FSM
    set_ep00(xem, base | START_BIT)  # start -> streamer primes, sequencer runs
    print(f"  DDR3 sequencer started (ep00 bit5=seq mode, bit2=start"
          f"{', bit1=infinite' if infinite else ''}"
          f"{', loop_limit=' + str(loop_limit) if loop_limit else ''})")


def run_long(xem, n_lines, dwell_ticks):
    """Stream the long ramp program and watch for either completion (seq_done)
    or a hang. A cold-start mis-read returns a line ~IMMUNE_LINES earlier, whose
    smaller absolute time drives time_stamp backward -> the sequencer stalls
    forever. So: reaching seq_done proves the streamer read every line correctly
    across the immune boundary with the heartbeat keeping the controller warm;
    a hang localizes the failure by the line index it froze at."""
    dwell_s = dwell_ticks / TICKS_PER_SEC
    runtime_s = n_lines * dwell_s
    boundary_s = IMMUNE_LINES * dwell_s
    timeout = runtime_s * 1.5 + 8.0
    hang_win = max(1.0, dwell_s * 400)   # unchanged this long while running = stuck
    print(f"  streaming {n_lines} lines @ {dwell_s * 1e3:.3f} ms/line "
          f"(~{runtime_s:.1f} s); crosses the 32 KiB immune boundary at line "
          f"{IMMUNE_LINES} (~{boundary_s:.1f} s)")
    print(f"  seq_done => whole stream correct (heartbeat OK); a freeze => "
          f"cold-start mis-read at that line\n")

    t0 = time.time()
    last_logic = None
    last_change = t0
    next_report = t0 + 1.0
    while True:
        now = time.time()
        xem.UpdateWireOuts()
        logic = xem.GetWireOutValue(LOGIC_WIRE)
        seq = xem.GetWireOutValue(SEQ_WIRE)
        if seq & SEQ_DONE_BIT:
            overflow = bool(seq & OVERFLOW_BIT)
            line_count = xem.GetWireOutValue(LINE_COUNT_WIRE)
            expected = n_lines + 1     # lines 0..terminator (see pulse_sequencer)
            print(f"    t={now - t0:6.1f}s  seq_done asserted (seq_count={seq & 0xFFFF}), "
                  f"drop flag={int(overflow)}, line_count={line_count} (expect {expected})")
            set_ep00(xem, 0)
            print("\n--- Long-stream result ---")
            # reaching seq_done is NOT sufficient: a dropped beat that missed the
            # terminator would silently skip lines yet still finish. Two independent
            # integrity checks close that: the streamer drop flag (overflow only)
            # and the line-pop count (any cause).
            if overflow:
                print(f"  RESULT: FAIL -- streamer DROP flag (0x2C bit17) is SET: a beat "
                      f"was pushed into a full FIFO and lost. FILL_MARGIN did not hold.")
                sys.exit(1)
            if line_count != expected:
                lost = expected - line_count
                print(f"  RESULT: FAIL -- sequencer popped {line_count} lines but "
                      f"expected {expected} ({'+' if lost < 0 else ''}{-lost} vs expected): "
                      f"{'lines LOST' if lost > 0 else 'DUPLICATE lines'} somewhere in the "
                      f"stream. Since the drop flag is 0, the loss is NOT FIFO overflow -- "
                      f"investigate the read path / streamer.")
                sys.exit(1)
            print(f"  RESULT: PASS -- streamed all {n_lines} lines past the immune "
                  f"boundary at line {IMMUNE_LINES}, seq_done asserted, drop flag 0, and "
                  f"the sequencer popped exactly {expected} lines. Every line accounted "
                  f"for -- no drops or duplicates from any cause.")
            return
        if logic != last_logic:
            last_logic = logic
            last_change = now
        if now >= next_report:
            approx_line = int((now - t0) / dwell_s) if dwell_s > 0 else 0
            print(f"    t={now - t0:6.1f}s  master_logic=0x{logic:08x}  "
                  f"~line {approx_line}"
                  f"{'  (PAST immune boundary)' if approx_line > IMMUNE_LINES else ''}")
            next_report = now + 1.0
        if now - last_change > hang_win:
            set_ep00(xem, 0)
            elapsed = now - t0
            approx = int(elapsed / dwell_s) if dwell_s > 0 else 0
            ch = last_logic & 0xFFF
            print("\n--- Long-stream result ---")
            if ch == 0:
                # real lines are never 0, so master=0 is the terminator/done
                # state -- but seq_done never latched.
                print(f"  RESULT: FAIL -- froze at master_logic=0 for >{hang_win:.1f}s "
                      f"near the end (~line {approx} of {n_lines}).")
                print("   * no real line is 0, so master=0 = the terminator/done "
                      "state was entered but seq_done never asserted: a stall AT the "
                      "terminator transition (the streamer did not deliver the "
                      "terminator line in time), NOT a cold-start mis-read.")
            else:
                # decode the frozen line from its channel: i == (ch-1) mod 4095,
                # picking the lap nearest the elapsed-time estimate.
                base = ch - 1
                k = round((approx - base) / 0xFFF) if dwell_s > 0 else 0
                stuck = max(base, base + k * 0xFFF)
                app = (stuck // 2) * 8
                vuln = (app >> 14) & 1
                print(f"  RESULT: FAIL -- froze at master_logic=0x{last_logic:08x} "
                      f"(channel 0x{ch:x}) for >{hang_win:.1f}s => stuck at line "
                      f"{stuck} of {n_lines}, app_addr 0x{app:x} "
                      f"(bit14={'SET/vulnerable' if vuln else 'clear/immune'}).")
                if vuln:
                    print(f"   * stall at a real line in the vulnerable region => a "
                          f"cold-start mis-read of the NEXT line (from ~{IMMUNE_LINES} "
                          f"earlier) drove time_stamp backward; the heartbeat did not "
                          f"keep the controller warm through this dwell.")
                else:
                    print("   * immune-region stall => not cold-start; suspect a "
                          "streamer underrun or program error.")
            sys.exit(1)
        if now - t0 > timeout:
            set_ep00(xem, 0)
            sys.exit(f"  RESULT: INCONCLUSIVE -- ran {timeout:.0f}s without "
                     f"seq_done or a clear freeze; raise the timeout or lower "
                     f"--lines/--dwell-ms.")
        time.sleep(0.01)


def run_loops(xem, n_lines, dwell_ticks, loops):
    """Finite-loop mode: run the program `loops` times (loop_limit) then stop.
    Verifies seq_count == loops, seq_done, drop flag 0, and line_count ==
    loops*(n_lines+1) + (loops-1) -- each loop pops n_lines+1 lines, plus one
    extra per loop boundary (the restart re-prime); sim-derived formula."""
    dwell_s = dwell_ticks / TICKS_PER_SEC
    loop_s = n_lines * dwell_s
    expect_lc = loops * (n_lines + 1) + (loops - 1)
    timeout = loop_s * loops * 1.5 + 8.0
    print(f"  {loops} loops of {n_lines} lines @ {dwell_s * 1e3:.3f} ms/line "
          f"(~{loop_s:.1f} s/loop, ~{loop_s * loops:.1f} s total)\n")
    t0 = time.time()
    last_seq = -1
    while time.time() - t0 < timeout:
        xem.UpdateWireOuts()
        seq = xem.GetWireOutValue(SEQ_WIRE)
        seq_count = seq & 0xFFFF
        if seq_count != last_seq:
            print(f"    t={time.time() - t0:6.1f}s  seq_count={seq_count}")
            last_seq = seq_count
        if seq & SEQ_DONE_BIT:
            overflow = bool(seq & OVERFLOW_BIT)
            lc = xem.GetWireOutValue(LINE_COUNT_WIRE)
            set_ep00(xem, 0)
            print(f"    seq_done at seq_count={seq_count}, drop flag={int(overflow)}, "
                  f"line_count={lc} (expect {expect_lc})")
            print("\n--- N-loop result ---")
            if seq_count == loops and not overflow and lc == expect_lc:
                print(f"  RESULT: PASS -- ran exactly {loops} loops, seq_done, drop flag 0, "
                      f"and line_count {lc} == {loops}*(n+1)+(n-1). Every line of every "
                      f"loop accounted for; restart/rewind/re-prime verified.")
                return
            print(f"  RESULT: FAIL -- seq_count {seq_count} (expect {loops}), drop flag "
                  f"{int(overflow)}, line_count {lc} (expect {expect_lc}).")
            sys.exit(1)
        time.sleep(0.02)
    set_ep00(xem, 0)
    sys.exit(f"  RESULT: FAIL -- {loops} loops did not finish within {timeout:.0f}s "
             f"(last seq_count={last_seq}).")


def run_loop(xem, n_lines, dwell_ticks, watch=8):
    """Infinite-loop mode: loop_limit=0, watch seq_count climb through `watch`
    iterations to confirm the restart/rewind/re-prime path repeats forever, then
    stop. Checks seq_count advances, seq_done never asserts, drop flag stays 0."""
    dwell_s = dwell_ticks / TICKS_PER_SEC
    loop_s = n_lines * dwell_s
    timeout = loop_s * (watch + 2) * 1.5 + 8.0
    print(f"  infinite loop of {n_lines} lines @ {dwell_s * 1e3:.3f} ms/line "
          f"(~{loop_s:.1f} s/loop); watching {watch} iterations\n")
    t0 = time.time()
    last_seq = -1
    done_seen = False
    while time.time() - t0 < timeout:
        xem.UpdateWireOuts()
        seq = xem.GetWireOutValue(SEQ_WIRE)
        seq_count = seq & 0xFFFF
        if seq & SEQ_DONE_BIT:
            done_seen = True
        if seq_count != last_seq:
            lc = xem.GetWireOutValue(LINE_COUNT_WIRE)
            ovf = bool(seq & OVERFLOW_BIT)
            print(f"    t={time.time() - t0:6.1f}s  seq_count={seq_count}  "
                  f"line_count={lc}  drop={int(ovf)}")
            last_seq = seq_count
            if seq_count >= watch:
                break
        time.sleep(0.02)
    overflow = bool(xem.GetWireOutValue(SEQ_WIRE) & OVERFLOW_BIT)
    set_ep00(xem, 0)   # stop
    print("\n--- Infinite-loop result ---")
    if last_seq >= watch and not done_seen and not overflow:
        print(f"  RESULT: PASS -- looped {last_seq}+ times without stopping (seq_done "
              f"never asserted), drop flag 0. Restart/rewind/re-prime repeats "
              f"indefinitely; stop it by clearing the start bit.")
        return
    sys.exit(f"  RESULT: FAIL -- last seq_count={last_seq} (wanted >={watch}), "
             f"seq_done_seen={done_seen}, drop flag={int(overflow)}.")


def main():
    def flag_value(name, default, cast):
        if name in args:
            i = args.index(name)
            try:
                return cast(args[i + 1])
            except (IndexError, ValueError):
                sys.exit(f"{name} needs a value")
        return default

    args = sys.argv[1:]
    fast = "--fast" in args
    long = "--long" in args
    loop = "--loop" in args
    loops_n = flag_value("--loops", None, int)     # finite loop count
    dwell_ms = flag_value("--dwell-ms", 2.0, float)
    n_lines_arg = flag_value("--lines", None, int)
    # loop modes want a smaller program so iterations are observable
    loop_mode = loop or (loops_n is not None)
    n_lines = n_lines_arg if n_lines_arg is not None else (1000 if loop_mode else 8192)
    # positional args = anything that is neither a flag nor a flag's value
    positional, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("--lines", "--dwell-ms", "--loops"):
            i += 2
        elif a.startswith("--"):
            i += 1
        else:
            positional.append(a)
            i += 1
    if not positional:
        sys.exit("usage: python ddr3_sequencer_bringup.py <photon.bit> "
                 "[--fast | --long | --loop | --loops N] [--lines N] [--dwell-ms X]")
    bit_path = positional[0]

    xem = connect(bit_path)   # ConfigureFPGA + wait for MIG calibration

    # Clean control state: every ep00 bit low, per-channel override mux off
    # (so logic_out == master_logic), loop limit 0 (one-shot).
    set_ep00(xem, 0x00000000)
    xem.SetWireInValue(0x02, 0, 0xFFFFFFFF)   # ep02: override enables off
    xem.SetWireInValue(0x03, 0, 0xFFFFFFFF)   # ep03: override values off
    xem.SetWireInValue(0x05, 0, 0xFFFFFFFF)   # ep05: loop_limit 0
    xem.UpdateWireIns()

    # ---- Loop modes (finite / infinite repeat of the program) ---------------
    if loop_mode:
        dwell_ticks = int(dwell_ms / 1e3 * TICKS_PER_SEC)
        prog, dwell_ticks = build_long_program(n_lines, dwell_ticks)
        kind = f"{loops_n} LOOPS" if loops_n is not None else "INFINITE LOOP"
        print(f"\n--- Phase 6c DDR3 sequencer bring-up: {kind} "
              f"({n_lines} lines, {dwell_ticks / TICKS_PER_SEC * 1e3:.3f} ms/line) ---")
        write_and_verify(xem, prog, min(256, len(prog)))
        if loops_n is not None:
            start_sequencer(xem, infinite=True, loop_limit=loops_n)
            run_loops(xem, n_lines, dwell_ticks, loops_n)
        else:
            start_sequencer(xem, infinite=True, loop_limit=0)
            run_loop(xem, n_lines, dwell_ticks)
        return

    # ---- Long heartbeat / cold-start-crossing test --------------------------
    if long:
        dwell_ticks = int(dwell_ms / 1e3 * TICKS_PER_SEC)
        prog, dwell_ticks = build_long_program(n_lines, dwell_ticks)
        print(f"\n--- Phase 6c DDR3 sequencer bring-up: LONG "
              f"({n_lines} lines, {dwell_ticks / TICKS_PER_SEC * 1e3:.3f} ms/line) ---")
        # verify only the first 256 words (low 32 KiB is cold-start immune for
        # the read path too); the write path itself is memtest-proven at scale.
        write_and_verify(xem, prog, min(256, len(prog)))
        start_sequencer(xem, infinite=False)
        run_long(xem, n_lines, dwell_ticks)
        return

    # ---- Short waveform-verification test -----------------------------------
    prog, expected = build_program(fast)
    mode = ("fast (scope/LA)" if fast
            else f"slow (host-observable, {len(expected)} states, varied dwells)")
    print(f"\n--- Phase 6c DDR3 sequencer bring-up: {mode} ---")

    write_and_verify(xem, prog, len(prog))     # full readback: program fits in 32 KiB
    start_sequencer(xem, infinite=False)
    print("  watch led_ext[0..3] walk; polling master_logic (0x2B) / seq_done (0x2C)\n")

    # Poll master_logic + seq_done and log every change.
    observed = []          # nonzero master_logic values, in order of appearance
    prev = None
    done = False
    seq_count = 0
    t0 = time.time()
    timeout = 3.0 if fast else 10.0
    while time.time() - t0 < timeout:
        xem.UpdateWireOuts()
        logic = xem.GetWireOutValue(LOGIC_WIRE)
        seq = xem.GetWireOutValue(SEQ_WIRE)
        seq_count = seq & 0xFFFF
        if logic != prev:
            t = time.time() - t0
            print(f"    t={t:5.2f}s  master_logic=0x{logic:08x}  led_ext[5:0]={logic & 0x3f:06b}")
            if logic != 0 and (not observed or observed[-1] != logic):
                observed.append(logic)
            prev = logic
        if seq & SEQ_DONE_BIT:
            print(f"    t={time.time() - t0:5.2f}s  seq_done asserted (seq_count={seq_count})")
            done = True
            break
        time.sleep(0.02 if fast else 0.05)

    # 5) Stop and clear control state.
    set_ep00(xem, 0x00000000)

    # 6) Verdict.
    print("\n--- Bring-up result ---")
    print(f"  observed nonzero states, in order: {[hex(v) for v in observed]}")
    print(f"  expected:                          {[hex(v) for v in expected]}")
    if fast:
        # Too quick to catch the intermediate states by host polling; the
        # meaningful check is that the sequencer ran to completion.
        if done:
            print("  RESULT: PASS -- DDR3 sequencer ran the program to seq_done.")
            print("  (fast mode: put a scope/LA on led_ext[0..2] to see the "
                  "40 ns-scale 0x01/0x02/0x04 pulses.)")
        else:
            sys.exit("  RESULT: FAIL -- seq_done never asserted (see notes below).")
    else:
        if observed == expected and done:
            print("  RESULT: PASS -- the DDR3-streamed program produced the exact "
                  "expected waveform, in order, and finished.")
        elif observed and observed == expected[:len(observed)] and not done:
            sys.exit("  RESULT: PARTIAL -- states so far are correct but the run "
                     "did not reach seq_done within the timeout.")
        else:
            print("  RESULT: FAIL -- observed waveform does not match. Notes:")
            print("   * all-zero / no transitions => streamer never primed "
                  "(program not read from DDR3), or start/seq-mode not asserted.")
            print("   * scrambled channels/times  => 64-bit line half-order out "
                  "of the streamer FIFO differs from the write packing "
                  "(the Phase 6c analogue of the Phase 6b byte-order match).")
            sys.exit(1)


if __name__ == "__main__":
    main()
