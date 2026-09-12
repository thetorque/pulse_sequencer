"""
hwconfig.py -- experiment hardware configuration (py3 port of the TTL half of
servers/pulser/hardwareConfiguration.py).

Just the facts the headless TTL driver needs: the channel name->number map (the
experiment's actual wiring) and the timing constants. The legacy class also
carried DDS board definitions and LabRAD/collection-mode state -- those belong
to M4 (DDS) and the server layer, and are intentionally omitted.

Edit CHANNELS to match your wiring; nothing here talks to hardware.
"""
from .wiremap import TIME_RESOLUTION_S
from .sequence import Sequence

CHANNEL_TOTAL = 32
MAX_SWITCHES = 1022
# Longest single-pass sequence: the 31-bit tick field caps absolute time at
# (2**31 - 1) * 40 ns ~= 85.9 s. Kept a touch under for the human-facing range.
SEQUENCE_TIME_RANGE_S = (0.0, 85.0)

# name -> hardware TTL channel number, ported verbatim from the legacy
# channelDict (RIKEN/lattice wiring). NOTE: a few names deliberately share a
# number in the original config (e.g. AO2 and B_x_sign both = 21) -- preserved
# as-is; a name->number map allows that (two labels, one physical line).
CHANNELS = {
    'ttl_0':            0,   # camera
    'sMOT_PROBE':       1,
    'sMOT_PROBE_SPIN':  2,
    'BIG_MOT_SH':       3,
    'sMOT_AO':          4,
    'BIG_MOT_AO':       5,
    '405_ECDL':         6,
    '405_Raman':        7,
    '435_Raman':        8,
    '266_SB':           9,
    'SP1':              10,
    'SP2':              11,
    'DiffCountTrigger': 16,   # differential PMT window trigger (FPGA CH_DIFF_TRIGGER)
    'AdvanceDDS':       18,
    'ResetDDS':         19,
    'AO1':              20,   # analog-board trigger
    'AO2':              21,   # analog-board trigger
    'B_x_sign':         21,
    'B_y_sign':         22,
    'B_z_sign':         23,
    'dummy_clock':      24,   # clock, for plotting only
}


def new_sequence():
    """A Sequence sized to this hardware, accepting channel names from CHANNELS."""
    return Sequence(channel_total=CHANNEL_TOTAL,
                    time_resolution_s=TIME_RESOLUTION_S,
                    max_switches=MAX_SWITCHES,
                    channel_map=CHANNELS)
