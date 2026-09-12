"""
test_client.py -- smoke-test the Data Vault server over LabRAD.

Creates a small dataset, writes a few rows, and reads them back, checking the
round-trip. Run the manager and the Data Vault server first (see README.md),
then:

    python test_client.py

Uses pylabrad's blocking client. Leaves a `test_py3` directory in the vault
(harmless -- it's just a test dataset on disk).
"""
import labrad


def main():
    cxn = labrad.connect()
    dv = cxn.data_vault                     # "Data Vault" -> data_vault

    dv.cd(['test_py3'], True)               # create/enter a test directory
    # one independent (x), one dependent (y = x^2); dependents are (label, legend, units)
    path, name = dv.new('smoke test', ['x'], [('y', '', 'arb')])
    print("created dataset:", name, "in", '/'.join(path))

    rows = [[float(x), float(x * x)] for x in range(5)]
    dv.add(rows)                            # *2v -- add multiple rows at once

    indeps, deps = dv.variables()
    print("independents:", [tuple(i) for i in indeps])
    print("dependents:  ", [tuple(d) for d in deps])

    back = dv.get()                         # read the rows back
    got = [list(r) for r in back]
    print("read back %d rows:" % len(got))
    for r in got:
        print("  ", r)

    assert len(got) == len(rows), "row count mismatch (%d vs %d)" % (len(got), len(rows))
    for (x0, y0), (x1, y1) in zip(rows, got):
        assert abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9, "value mismatch"

    print("PASS -- Data Vault create / add / read-back works (HDF5 on disk)")


if __name__ == "__main__":
    main()
