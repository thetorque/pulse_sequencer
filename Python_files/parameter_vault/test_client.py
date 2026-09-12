"""
test_client.py -- smoke-test the ParameterVault server over LabRAD.

Seeds a couple of parameters directly into the registry, tells the server to
reload, then reads and writes them back through the ParameterVault settings.
Run the manager and the ParameterVault server first (see README.md), then:

    python test_client.py

Uses pylabrad's blocking client. Cleans up the test collection at the end.
"""
import labrad

COLLECTION = 'TestCollection'
REG_PATH = ['', 'Servers', 'Parameter Vault', COLLECTION]


def main():
    cxn = labrad.connect()
    reg = cxn.registry
    pv = cxn.parametervault    # pylabrad lowercases the name; no camelCase split

    # seed two typed parameters straight into the registry
    reg.cd(REG_PATH, True)
    reg.set('freq', ('parameter', [0.0, 100.0, 42.0]))   # (min, max, current)
    reg.set('label', ('string', 'hello'))
    pv.reload_parameters()

    # collections / names
    collections = list(pv.get_collections())
    print("collections:", collections)
    names = sorted(pv.get_parameter_names(COLLECTION))
    print("names in %s: %s" % (COLLECTION, names))
    assert COLLECTION in collections, "collection not loaded"
    assert names == ['freq', 'label'], "parameter names mismatch"

    # checked reads reduce to the effective value
    freq = pv.get_parameter(COLLECTION, 'freq')
    label = pv.get_parameter(COLLECTION, 'label')
    print("freq (checked):", freq, " label:", label)
    assert abs(freq - 42.0) < 1e-9 and label == 'hello', "read mismatch"

    # write a new in-bounds value, read it back
    pv.set_parameter(COLLECTION, 'freq', 55.0)
    freq2 = pv.get_parameter(COLLECTION, 'freq')
    print("freq after set:", freq2)
    assert abs(freq2 - 55.0) < 1e-9, "write did not stick"

    # out-of-bounds write should be rejected
    try:
        pv.set_parameter(COLLECTION, 'freq', 999.0)
        raise AssertionError("out-of-bounds write was NOT rejected")
    except Exception as e:
        if "out of bound" not in str(e).lower():
            raise
        print("out-of-bounds correctly rejected")

    print("PASS -- ParameterVault load / get / set / bounds all work")

    # best-effort cleanup: delete the seeded keys then the test collection
    try:
        reg.cd(REG_PATH)
        _, keys = reg.dir()
        for k in keys:
            reg.del_(k)
        reg.cd(['', 'Servers', 'Parameter Vault'])
        reg.rmdir(COLLECTION)
    except Exception as e:
        print("(cleanup skipped: %s -- remove %s from the registry by hand if "
              "you care)" % (e, '/'.join(REG_PATH)))


if __name__ == "__main__":
    main()
