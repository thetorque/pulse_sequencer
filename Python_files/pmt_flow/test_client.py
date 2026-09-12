"""
test_client.py -- smoke-test NormalPMTFlow over LabRAD (Normal mode).

Exercises the whole higher-level path: NormalPMTFlow -> Pulser (on-FPGA
synthetic photon source) -> Data Vault. No detector needed. Run the manager,
the Pulser, the Data Vault, and the NormalPMTFlow servers first, then:

    python test_client.py

Uses pylabrad's blocking client. Leaves a dataset in the vault under
'PMT Counts' (harmless).
"""
import time

import labrad
from labrad.units import s


def main():
    cxn = labrad.connect()
    pf = cxn.normalpmtflow            # "NormalPMTFlow" -> normalpmtflow

    lo, hi = pf.get_time_length_range()
    print("collection-time range: %.3f .. %.3f s" % (lo, hi))

    pf.set_mode('Normal')
    print("mode:", pf.get_current_mode())
    pf.set_time_length(0.05 * s)      # 50 ms windows
    pf.record_data()                  # opens a dataset + starts the recording loop
    print("recording:", pf.is_running())

    time.sleep(1.5)                   # let a few windows accumulate + log to DV
    ds = pf.current_data_set()
    print("dataset:", ds)

    avg = pf.get_next_counts('ON', 5, True)   # average of 5 ON count rates
    print("avg ON count rate: %.1f KC/s" % avg)

    pf.stop_recording()
    print("recording after stop:", pf.is_running())

    # 100 kHz synthetic source over a 50 ms window ~= 5000 counts = 100 KC/s
    ok = bool(ds) and 20.0 < avg < 500.0
    print("PASS -- NormalPMTFlow -> Pulser -> Data Vault works"
          if ok else "CHECK -- see values above")


if __name__ == "__main__":
    main()
