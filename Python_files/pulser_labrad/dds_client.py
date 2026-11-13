"""
dds_client.py -- bench check of the Pulser server's DDS settings over LabRAD
(roadmap 4.3): scalabrad -> Pulser server -> pulser3.dds_sequence -> pipe 0x81
-> backplane -> DDS board.

Run the scalabrad manager and the Pulser server first (README.md), DDS board on
dds_top, frequency counter on the RF output, then:

    python dds_client.py [--manual-mhz 70] [--tones 75,125]

1. Manual control: Frequency / Amplitude / Output on hwconfig's first DDS channel
   -> the counter shows the manual tone (8 s), then RF off (4 s).
2. A sequence with Add DDS Pulses, Program Sequence, two Start Single runs:
      0-2 s manual tone | 2-5 s tone 1 | 5-8 s tone 2 (back-to-back) | 8-10 s off
   While it is loaded, a manual change must be refused (DDS lock).
3. Error path: two DDS changes 2 us apart must make Program Sequence fail.
4. Stop Sequence -> lock released -> manual tone back on, then off.

Each step prints what the counter should show.
"""
import argparse
import time

import labrad
from labrad.units import WithUnit


def U(v, unit):
    return WithUnit(v, unit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual-mhz", type=float, default=70.0)
    ap.add_argument("--tones", default="75,125")
    a = ap.parse_args()
    t1, t2 = [float(x) for x in a.tones.split(",")]
    fails = []

    cxn = labrad.connect()
    p = cxn.pulser
    chans = p.get_dds_channels()
    print("DDS channels:", chans)
    ch = chans[0]
    print("frequency range", p.get_dds_frequency_range(ch), "MHz;",
          "amplitude range", p.get_dds_amplitude_range(ch), "dBm")

    # ---- 1. manual -------------------------------------------------------
    p.frequency(ch, U(a.manual_mhz, 'MHz'))
    p.amplitude(ch, U(0.0, 'dBm'))
    p.output(ch, True)
    print(f"[1] manual: counter should read {a.manual_mhz:g} MHz for 8 s ...")
    time.sleep(8)
    p.output(ch, False)
    print("[1] manual OFF: counter should stop for 4 s ...")
    time.sleep(4)
    p.output(ch, True)             # manual ON -> row 0 of the sequence

    # ---- 2. sequence -----------------------------------------------------
    p.new_sequence()
    # both accepted forms (a LabRAD list is homogeneous, so one call each)
    p.add_dds_pulses([(ch, U(2.0, 's'), U(3.0, 's'), U(t1, 'MHz'), U(0.0, 'dBm'))])
    p.add_dds_pulses([(ch, U(5.0, 's'), U(3.0, 's'), U(t2, 'MHz'), U(0.0, 'dBm'),
                       U(0.0, 'deg'), U(0.0, 'MHz'), U(0.0, 'dB'))])
    for t in (2.0, 5.0, 8.0):
        p.add_ttl_pulse('ttl_0', U(t, 's'), U(1e-6, 's'))       # scope marker
    p.extend_sequence_length(U(10.0, 's'))
    print("[2] Human Readable DDS:")
    for name, f, dbm in p.human_readable_dds():
        print(f"      {name}: {f:g} MHz, {dbm:g} dBm")
    p.program_sequence()
    try:
        p.frequency(ch, U(90.0, 'MHz'))
        fails.append("manual change was NOT refused while a DDS sequence is loaded")
    except Exception as e:
        print("[2] manual change refused while locked: OK")
    for run in (1, 2):
        print(f"[2] run {run}: {a.manual_mhz:g} MHz (0-2 s) -> {t1:g} (2-5 s) -> "
              f"{t2:g} (5-8 s) -> off (8-10 s)")
        p.start_single()
        if not p.wait_sequence_done(20.0):
            fails.append(f"run {run} did not finish")
        time.sleep(2)

    # ---- 3. error path ---------------------------------------------------
    p.new_sequence()
    p.add_dds_pulses([(ch, U(1e-3, 's'), U(10e-6, 's'), U(t1, 'MHz'), U(0.0, 'dBm')),
                      (ch, U(1.012e-3, 's'), U(10e-6, 's'), U(t2, 'MHz'), U(0.0, 'dBm'))])
    try:
        p.program_sequence()
        fails.append("2 us DDS spacing was NOT rejected")
    except Exception as e:
        print("[3] 2 us spacing rejected: OK --", str(e).splitlines()[-1][:120])

    # ---- 4. unlock -------------------------------------------------------
    p.stop_sequence()
    p.frequency(ch, U(a.manual_mhz, 'MHz'))
    print(f"[4] unlocked; manual {a.manual_mhz:g} MHz back on for 5 s ...")
    time.sleep(5)
    p.output(ch, False)
    print("[4] manual OFF")

    if fails:
        print("FAIL:", "; ".join(fails))
    else:
        print("PASS (server side) -- confirm the counter followed every step")


if __name__ == "__main__":
    main()
