"""
seed_parameters.py -- put the parameters the example experiments need into the
ParameterVault.

The 'LED Blink (from ParameterVault)' experiment reads LedBlink.on_time from the
vault. Parameters are seeded straight into the LabRAD registry (the vault's store)
and then the server is told to reload -- the same approach as the ParameterVault
test client. Run once with the manager + ParameterVault up:

    python experiment/seed_parameters.py
"""
import labrad
from labrad.units import WithUnit

COLLECTION = 'LedBlink'
REG_PATH = ['', 'Servers', 'Parameter Vault', COLLECTION]


def main():
    cxn = labrad.connect()
    reg = cxn.registry
    reg.cd(REG_PATH, True)
    # a 'parameter' typed value: (min, max, current) -- here in seconds
    reg.set('on_time', ('parameter', [WithUnit(0.02, 's'), WithUnit(2.0, 's'), WithUnit(0.25, 's')]))
    cxn.parametervault.reload_parameters()
    print("seeded %s.on_time = 0.25 s  (range 0.02 .. 2.0 s)" % COLLECTION)
    print("now run 'LED Blink (from ParameterVault)' in ScriptScanner")


if __name__ == '__main__':
    main()
