"""
test_client.py -- minimal py3 LabRAD client that proves the modern stack
end-to-end: scalabrad manager -> Pulser server -> pulser3 -> XEM7305.

Run the scalabrad manager and the Pulser server first (see README.md), then:

    python test_client.py

Uses pylabrad's blocking client (simplest for a smoke test). Setting names map
to methods with spaces -> underscores, lowercased (LabRAD convention), e.g.
"Add TTL Pulse" -> p.add_ttl_pulse.
"""
import labrad
from labrad.units import s


def main():
    cxn = labrad.connect()            # manager from env (LABRAD*) or localhost
    p = cxn.pulser                    # the Pulser server

    chans = p.get_channels()
    print("Pulser channels:", list(chans)[:6], "...")

    # a tiny TTL program on real channels, walking a couple of lines
    p.new_sequence()
    p.add_ttl_pulse('sMOT_PROBE', 0.1 * s, 0.5 * s)
    p.add_ttl_pulse('BIG_MOT_SH', 0.3 * s, 0.5 * s)
    p.extend_sequence_length(1.0 * s)

    p.program_sequence()              # compile -> DDR3
    print("programmed; starting single run ...")
    p.start_single()

    done = p.wait_sequence_done(5.0)
    print("sequence done:", done)
    if done:
        print("PASS -- scalabrad -> Pulser server -> pulser3 -> FPGA works end to end")
    else:
        print("FAIL -- sequence did not report done (check the server log)")


if __name__ == "__main__":
    main()
