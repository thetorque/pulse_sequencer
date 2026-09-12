"""
test_client.py -- smoke-test ScriptScanner over LabRAD.

Exercises the orchestrator with the bundled hardware-free experiments:
  1. list available scripts + their parameters
  2. queue a single 'Sleep Experiment', watch its progress to completion
  3. queue another, then Stop it mid-run
  4. (needs Data Vault) scan 'PMT Point' over a frequency -> a lineshape dataset

Start the manager + ScriptScanner first (and the Data Vault for step 4), then:

    python test_client.py

Uses pylabrad's blocking client. NB pylabrad lowercases setting NAMES and turns
non-alphanumerics into underscores but does NOT split camelCase, so 'New
Experiment' -> new_experiment, 'Get Progress' -> get_progress, etc.
"""
import time

import labrad


def wait_done(sc, ident, timeout=30.0):
    """Poll Get Progress until the script leaves the running set (or times out)."""
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        running = dict(sc.get_running())
        if ident not in running:
            return last
        status, pct = sc.get_progress(ident)
        if (status, round(pct)) != last:
            print("   [%d] %-9s %5.1f%%" % (ident, status, pct))
            last = (status, round(pct))
        time.sleep(0.2)
    return last


def main():
    cxn = labrad.connect()
    sc = cxn.scriptscanner              # "ScriptScanner" -> scriptscanner

    print("available scripts:")
    scripts = sc.get_available_scripts()
    for s in scripts:
        print("  -", s)
    assert 'Sleep Experiment' in scripts, "Sleep Experiment not registered"

    print("params of 'PMT Point':", list(sc.get_script_parameters('PMT Point')))

    # --- 1) single run to completion ---------------------------------
    print("\nqueueing a single 'Sleep Experiment' ...")
    ident = sc.new_experiment('Sleep Experiment')   # setting 10 'New Experiment'
    print("  queued id =", ident)
    last = wait_done(sc, ident)
    assert last is not None and last[0] in ('Finished', 'Stopped'), \
        "unexpected final status: %r" % (last,)
    print("  final:", last)

    # --- 2) stop mid-run ---------------------------------------------
    print("\nqueueing another and stopping it mid-run ...")
    ident = sc.new_experiment('Sleep Experiment')
    time.sleep(0.8)                     # let it get going
    running = dict(sc.get_running())
    if ident in running:
        sc.stop_script(ident)          # setting 21 'Stop Script'
        print("  requested stop")
    wait_done(sc, ident)
    print("  stopped OK")

    # --- 3) a scan into the Data Vault (needs Data Vault) ------------
    try:
        cxn.data_vault
    except Exception:
        print("\n(Data Vault not running -- skipping the scan test)")
    else:
        print("\nscanning 'PMT Point' over Spectrum.frequency (-3..3 kHz, 21 pts) ...")
        # scan == measure -> scan_experiment_1D; result saved vs frequency
        ident = sc.new_script_scan('PMT Point', 'PMT Point',
                                   'Spectrum', 'frequency',
                                   -3.0, 3.0, 21, 'kHz')
        wait_done(sc, ident, timeout=60.0)
        print("  scan done -- look under ['','ScriptScanner', <date>] in the grapher")

    print("\nPASS")


if __name__ == '__main__':
    main()
