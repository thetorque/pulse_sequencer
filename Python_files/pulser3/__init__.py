"""
pulser3 -- headless Python-3 host driver for the XEM7305 (2026) pulse sequencer.

Replaces the FPGA-facing half of the legacy LabRAD stack (../servers/pulser)
with a plain-Python-3 package: no LabRAD, Twisted, or Qt. Targets the 2026
bitstream's endpoint map, reusing the hardware-proven DDR3 pipe primitives.

Typical use:
    from pulser3 import Driver, line
    d = Driver()
    d.connect("photon.bit")
    d.load_program([line(0, 0x001), line(25_000_000, 0x003), 0])  # + auto-pad
    d.start_single()
    d.wait_done()

Off the bench (no `ok` module), wiremap/sequence still import for unit tests;
only Driver.connect() and the run methods touch hardware.
"""
from .driver import Driver, PulserError
from .wiremap import line, TICKS_PER_SEC, TIME_RESOLUTION_S

__all__ = ["Driver", "PulserError", "line", "TICKS_PER_SEC", "TIME_RESOLUTION_S"]
