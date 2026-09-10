"""
_ddr3.py -- bridge to the hardware-proven DDR3 pipe primitives.

The DDR3 write/read path (program upload, calibration wait, write-verify
readback) is intricate: it encodes three MIG-7 read gotchas and a
calibration-race fix that were debugged and cleared on silicon in Phase 6b/6c.
Rather than fork that logic (and risk it drifting from the FPGA it must match),
this module re-uses the proven implementation in

    VHDL_files/XEM7305_Pulser_2026_09_07/test/ddr3_roundtrip_demo.py

as the single source of truth, exposing just the four primitives the driver
needs. The import is LAZY (inside functions) so wiremap/sequence/hwconfig stay
importable off the bench, where the compiled `ok` module isn't installed.

MIGRATION NOTE (planned M1.5): once the host package must deploy standalone on
the experiment-control PC (away from this repo), lift `connect`,
`reset_ddr3`, `write_words`, `read_words` into this file and flip the test
scripts to import them from here -- making pulser3 the canonical low-level and
the test tree a consumer, not the source.
"""
import os
import sys

_TEST_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "VHDL_files", "XEM7305_Pulser_2026_09_07", "test",
    )
)

_mod = None


def _lowlevel():
    """Import (once) and return the proven ddr3_roundtrip_demo module.

    Imports `ok` transitively, so this only works where the FrontPanel Python
    module is installed -- i.e. on the machine wired to the XEM7305.
    """
    global _mod
    if _mod is None:
        if _TEST_DIR not in sys.path:
            sys.path.insert(0, _TEST_DIR)
        import ddr3_roundtrip_demo as _m  # noqa: E402  (lazy on purpose)
        _mod = _m
    return _mod


def connect(bit_path):
    """ConfigureFPGA(bit_path) + wait for MIG DDR3 calibration; return xem."""
    return _lowlevel().connect(bit_path)


def reset_ddr3(xem):
    """Reset the DDR3 write/read pointers and pulse FIFO for a clean run."""
    return _lowlevel().reset_ddr3(xem)


def write_words(xem, words):
    """Write a list of 64-bit ints (EVEN count) to DDR3 @ address 0."""
    return _lowlevel().write_words(xem, words)


def read_words(xem, n_words, reset_fifo=True):
    """Read back the first n_words 64-bit words from DDR3 @ address 0."""
    return _lowlevel().read_words(xem, n_words, reset_fifo=reset_fifo)
