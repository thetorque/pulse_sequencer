"""
dds.py -- host side of the DDS backplane bus (M4, part 1: encoding + transport).

Implements DDS_BUS_CONTRACT.md v0.4 (repo root). Pure Python except for the three
small functions at the bottom that talk to an `ok.FrontPanel` object; everything
else is unit-tested without hardware (python -m pulser3.test_dds).

Layers:
  Row          one DDS setpoint (frequency, phase, VGA amplitude code, RF on/off)
               -> 11-byte config_ram row (§3)
  frames       bus frames for one board / broadcast (§4, §5):
               write_rows, reset, step, write_reg, identify, clear_status, nop
  pack()       frames -> the BTPipeIn 0x81 byte stream: LEN16-prefixed records,
               padded to the pipe block size (§7)
  VgaCal       dBm -> VGA code (per-board calibration; the board never sees dBm)

Not here yet (M4 part 2): the sequence parser (legacy parseDDS port), the LabRAD
server settings and the GUI.
"""
from dataclasses import dataclass

from . import wiremap as W

F_SYSCLK_HZ = 1e9            # AD9912 direct SYSCLK on board 8 (bench generator)
BROADCAST = 0x1F
ROW_BYTES = 11
N_ROWS = 8192                # config_ram depth per board
VGA_MAX = 0xFFF

CMD_NOP, CMD_WRITE_ROWS, CMD_RESET, CMD_STEP, CMD_WRITE_REG = 0x00, 0x01, 0x02, 0x03, 0x04
CMD_IDENTIFY, CMD_CLEAR_STATUS = 0x05, 0x06                     # v0.4


class DDSError(Exception):
    pass


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def ftw_from_hz(freq_hz, f_sysclk_hz=F_SYSCLK_HZ):
    """48-bit frequency tuning word, rounded to nearest (error <= 1.8 uHz @ 1 GHz)."""
    if not 0 <= freq_hz < f_sysclk_hz / 2:
        raise DDSError(f"frequency {freq_hz} Hz outside 0 .. f_sysclk/2")
    return int(round(freq_hz / f_sysclk_hz * 2**48)) & (2**48 - 1)


def hz_from_ftw(ftw, f_sysclk_hz=F_SYSCLK_HZ):
    return ftw * f_sysclk_hz / 2**48


def pow16_from_deg(phase_deg):
    """POW16 = fraction of a turn (§3); the AD9912 uses the top 14 bits."""
    return int(round((phase_deg % 360.0) / 360.0 * 2**16)) & 0xFFFF


@dataclass(frozen=True)
class Row:
    freq_hz: float = 0.0
    phase_deg: float = 0.0
    vga: int = 0                  # MCP4821 code (amplitude), 0..0xFFF
    rf_on: bool = False
    f_sysclk_hz: float = F_SYSCLK_HZ

    def to_int(self):
        if not 0 <= self.vga <= VGA_MAX:
            raise DDSError(f"VGA code {self.vga} outside 0..0xFFF")
        ftw = ftw_from_hz(self.freq_hz, self.f_sysclk_hz)
        pw = pow16_from_deg(self.phase_deg)
        # [87:40] FTW48 | [39:24] POW16 | [23:12] VGA12 | [11:8] rsvd | [7:0] CTRL8
        return (ftw << 40) | (pw << 24) | (self.vga << 12) | (1 if self.rf_on else 0)

    def to_bytes(self):
        return self.to_int().to_bytes(ROW_BYTES, "big")

    @property
    def exact_hz(self):
        return hz_from_ftw(ftw_from_hz(self.freq_hz, self.f_sysclk_hz), self.f_sysclk_hz)


OFF = Row()                       # 0 Hz, VGA 0, RF switch open (the power-up state)


# ---------------------------------------------------------------------------
# frames (one CS-low period on the bus each)
# ---------------------------------------------------------------------------
def _hdr(addr):
    if not 0 <= addr <= 0x1F:
        raise DDSError(f"board address {addr} outside 0..31 (31 = broadcast)")
    return bytes([addr & 0x1F])       # version bits [7:5] = 000


def write_rows(addr, start, rows):
    """WRITE_ROWS: rows land at start, start+1, ... (wraps at 8192)."""
    if not 0 <= start < N_ROWS:
        raise DDSError(f"start row {start} outside 0..{N_ROWS-1}")
    rows = list(rows)
    if not rows:
        raise DDSError("write_rows needs at least one row")
    return _hdr(addr) + bytes([CMD_WRITE_ROWS]) + start.to_bytes(2, "big") + \
        b"".join(r.to_bytes() for r in rows)


def reset(addr=BROADCAST):
    """RESET: row_ptr = 0 and row 0 applied (soft RAMRESET)."""
    return _hdr(addr) + bytes([CMD_RESET])


def step(addr=BROADCAST):
    """STEP: same as a STEPNEXT edge (soft step; sequences use the TTL line)."""
    return _hdr(addr) + bytes([CMD_STEP])


def write_reg(addr, reg, data):
    """WRITE_REG: raw AD9912 register write; the board then re-applies its live row."""
    if not 0 <= reg <= 0x1FFF or not 0 <= data <= 0xFF:
        raise DDSError("register address must be 13-bit, data 8-bit")
    return _hdr(addr) + bytes([CMD_WRITE_REG]) + reg.to_bytes(2, "big") + bytes([data])


def identify(addr, seconds=10):
    """IDENTIFY (v0.4): blink the board's D6 LED amber for ~`seconds` (0 = stop)."""
    if not 0 <= seconds <= 255:
        raise DDSError("identify seconds must be 0..255")
    return _hdr(addr) + bytes([CMD_IDENTIFY, int(seconds)])


def clear_status(addr=BROADCAST):
    """CLEAR_STATUS (v0.4): clear the latched error LEDs (frame error, step overrun)."""
    return _hdr(addr) + bytes([CMD_CLEAR_STATUS])


def nop(addr=BROADCAST, payload=b""):
    return _hdr(addr) + bytes([CMD_NOP]) + bytes(payload)


def set_dac_fsc(addr, fsc):
    """DAC full-scale current (10-bit) as two WRITE_REG frames (0x040C/0x040B)."""
    if not 0 <= fsc <= 0x3FF:
        raise DDSError("FSC is 10-bit")
    return [write_reg(addr, 0x040C, fsc >> 8), write_reg(addr, 0x040B, fsc & 0xFF)]


def program_board(addr, rows, start=0, chunk=256):
    """Frames that load a whole table, split so no single frame is huge."""
    rows = list(rows)
    if start + len(rows) > N_ROWS:
        raise DDSError(f"{len(rows)} rows from {start} exceed the {N_ROWS}-row table")
    return [write_rows(addr, start + i, rows[i:i + chunk]) for i in range(0, len(rows), chunk)]


# ---------------------------------------------------------------------------
# pipe stream (§7): LEN16 + frame, padded to whole blocks
# ---------------------------------------------------------------------------
def pack(frames, block=W.DDS_PIPE_BLOCK):
    """frames -> bytes for one WriteToBlockPipeIn(0x81, block, ...).

    Every record is LEN16 (big-endian) + frame. The tail is padded to a multiple of
    `block` so that the stream ENDS ON A RECORD BOUNDARY (the FPGA parser keeps its
    state across writes): an even gap is filled with LEN=0 padding records (two zero
    bytes each); an odd gap with one NOP frame of the right size (a NOP is a real but
    harmless bus frame).
    """
    if block % 4 or block < 16:
        raise DDSError("block must be a multiple of 4 and >= 16")
    out = bytearray()
    for f in frames:
        if not 2 <= len(f) <= 0xFFFF:
            raise DDSError(f"frame length {len(f)} outside 2..65535")
        out += len(f).to_bytes(2, "big") + f
    gap = (-len(out)) % block
    if gap % 2:                        # odd: one NOP record (2 + 2 + k bytes, k odd)
        if gap < 5:
            gap += block
        k = gap - 4
        out += (2 + k).to_bytes(2, "big") + nop(BROADCAST, b"\x00" * k)
    else:
        out += b"\x00" * gap           # LEN=0 records
    assert len(out) % block == 0
    return bytes(out)


def unpack(stream):
    """Reference parser (mirrors dds_bus_tx.vhd): stream -> list of bus frames."""
    frames, i = [], 0
    while i + 2 <= len(stream):
        n = int.from_bytes(stream[i:i + 2], "big")
        i += 2
        if n == 0:
            continue
        if i + n > len(stream):
            raise DDSError("stream ends inside a record")
        frames.append(bytes(stream[i:i + n]))
        i += n
    if i != len(stream):
        raise DDSError("dangling byte at end of stream")
    return frames


# ---------------------------------------------------------------------------
# amplitude calibration
# ---------------------------------------------------------------------------
@dataclass
class VgaCal:
    """dBm (into 50 ohm) -> VGA code, linear in code at a reference frequency.

    Default = board 8 at 50 MHz, FSC 0x200 (measured 2026-11-07): 0xB40 ~ 0 dBm,
    ~61 codes/dB, valid about -40 .. +15 dBm. PROVISIONAL: a per-board,
    per-frequency table (roadmap 1.6) will replace this; the board's response is
    not flat (sweep: -27 dBm @ 10 MHz .. ~+2 dBm @ 100-200 MHz at the same code).
    """
    code_at_0dbm: int = 0xB40
    codes_per_db: float = 61.0
    max_dbm: float = 15.0
    min_dbm: float = -40.0

    def code(self, dbm, freq_hz=None):
        if not self.min_dbm <= dbm <= self.max_dbm:
            raise DDSError(f"{dbm} dBm outside calibrated {self.min_dbm}..{self.max_dbm}")
        c = int(round(self.code_at_0dbm + dbm * self.codes_per_db))
        return max(0, min(VGA_MAX, c))


def row_dbm(freq_hz, dbm, phase_deg=0.0, cal=None, rf_on=True):
    """Convenience: a Row from frequency + dBm through a VgaCal."""
    cal = cal or VgaCal()
    return Row(freq_hz=freq_hz, phase_deg=phase_deg, vga=cal.code(dbm, freq_hz), rf_on=rf_on)


# ---------------------------------------------------------------------------
# hardware (needs an ok.FrontPanel opened on the Phase-4 bitstream)
# ---------------------------------------------------------------------------
def send(xem, frames, block=W.DDS_PIPE_BLOCK):
    """Write frames to BTPipeIn 0x81. Returns the byte count written."""
    data = bytearray(pack(frames, block))
    n = xem.WriteToBlockPipeIn(W.DDS_PIPE, block, data)
    if n != len(data):
        raise DDSError(f"WriteToBlockPipeIn(0x81) returned {n}, expected {len(data)}")
    return n


def trigger_step(xem):
    """120 ns STEPNEXT pulse to all boards (TriggerIn 0x40 bit 6)."""
    xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_DDS_STEP_BIT)


def trigger_reset(xem):
    """120 ns RAMRESET pulse to all boards (TriggerIn 0x40 bit 7)."""
    xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_DDS_RESET_BIT)


def clear_pipe(xem):
    """Flush the 0x81 frame FIFO + serializer (TriggerIn 0x40 bit 8)."""
    xem.ActivateTriggerIn(W.TRIG_RESET, W.TRIG_DDS_CLEAR_BIT)
