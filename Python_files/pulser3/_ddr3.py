"""
_ddr3.py -- thin lazy seam over the DDR3 pipe primitives.

Since M1.5 the primitives live in this package (ddr3_backend.py), so pulser3 no
longer reaches into the FPGA test tree. This module stays as the driver's stable
import point and, crucially, keeps the `ok` import LAZY: ddr3_backend does
`import ok` at its top, so importing it is deferred to first hardware use --
letting wiremap/sequence/hwconfig (and Driver construction) import on a machine
with no FrontPanel SDK for off-bench unit tests.
"""
_mod = None


def _backend():
    global _mod
    if _mod is None:
        from . import ddr3_backend as _m   # imports `ok` -- hardware only
        _mod = _m
    return _mod


def connect(bit_path):
    """ConfigureFPGA(bit_path) + wait for MIG DDR3 calibration; return xem."""
    return _backend().connect(bit_path)


def reset_ddr3(xem):
    """Reset the DDR3 write/read pointers and pulse FIFO for a clean run."""
    return _backend().reset_ddr3(xem)


def write_words(xem, words):
    """Write a list of 64-bit ints (EVEN count) to DDR3 @ address 0."""
    return _backend().write_words(xem, words)


def read_words(xem, n_words, reset_fifo=True):
    """Read back the first n_words 64-bit words from DDR3 @ address 0."""
    return _backend().read_words(xem, n_words, reset_fifo=reset_fifo)
