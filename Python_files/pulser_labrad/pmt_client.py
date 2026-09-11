"""
pmt_client.py -- exercise the Pulser server's PMT counting settings over LabRAD.

Proves the PMT half of the stack end-to-end (scalabrad -> Pulser server ->
pulser3 PMT datapath -> XEM7305 synthetic source), the same way test_client.py
proves the TTL-sequence half. Run the manager and the Pulser server first
(see README.md), then:

    python pmt_client.py

Uses the on-FPGA synthetic photon source (bring-up), so it needs no detector.
Normal mode at a known sim rate + gate => a predictable count; differential
mode is gated by a running sequence's channel 16.
"""
import time

import labrad


def normal_mode(p):
    print("\n== Normal mode ==")
    p.set_mode('Normal')
    p.set_pmt_synthetic(True)
    p.set_pmt_sim_rate(1.0e5)          # 100 kHz synthetic photons
    p.set_collection_time(0.010, 'Normal')   # 10 ms gate -> ~1000 counts/window
    p.reset_fifo_normal()
    time.sleep(0.3)                    # let a few windows accumulate
    counts = p.get_pmt_counts()
    print("collection mode:", p.get_collection_mode())
    print("windows read:", len(counts))
    for kc, status, t in list(counts)[:5]:
        print("  %.1f KC/s  %s" % (kc, status))
    # 100 kHz * 10 ms = 1000 counts = 100 KC/s expected (approx)
    if counts:
        kc0 = counts[0][0]
        ok = 50.0 < kc0 < 200.0
        print("first window %.1f KC/s -> %s" % (kc0, "PASS" if ok else "CHECK"))
        return ok
    print("no windows read -- CHECK (is the datapath counting?)")
    return False


def timetags(p):
    print("\n== Timetags ==")
    print("resolution:", p.get_timetag_resolution(), "s")
    p.set_pmt_synthetic(True)
    p.set_pmt_sim_rate(1.0e4)          # 10 kHz -> sparse, easy to read
    p.reset_timetags()
    p.record_timetags(True)
    time.sleep(0.1)
    p.record_timetags(False)
    tags = p.get_timetags()
    print("timetags read:", len(tags))
    for t in list(tags)[:5]:
        print("  %.9f s" % t)
    return len(tags) > 0


def main():
    cxn = labrad.connect()
    p = cxn.pulser
    ok_n = normal_mode(p)
    ok_t = timetags(p)
    print("\nPMT over LabRAD:",
          "PASS" if (ok_n and ok_t) else "CHECK (see per-section notes)")


if __name__ == "__main__":
    main()
