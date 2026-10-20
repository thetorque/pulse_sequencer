# pico_sspi_cont.py -- send 0x7A burst + bitstream as ONE continuous SPI transaction
# (no clock gap between command and data). Reuses the comment-header bytes just
# before the preamble to hold the 0x7A command, so only ONE 99 KB buffer is needed.

from machine import Pin, SPI
import time, os

BITFILE = "led_static_c.bit"

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)

BSE = {0: "none", 1: "ID", 2: "CMD", 3: "CRC", 4: "PRMB", 5: "ABRT", 6: "OVFL", 7: "SDM"}

# one buffer only -- read directly into a pre-sized bytearray (no double copy)
_sz = os.stat(BITFILE)[6]
buf = bytearray(_sz)
with open(BITFILE, "rb") as f:
    f.readinto(buf)

sync = buf.find(b"\xbd\xb3")
start = sync
while start > 0 and buf[start - 1] == 0xFF:
    start -= 1
cmd = start - 4                       # put 0x7A 00 00 00 right before the preamble
buf[cmd:start] = b"\x7A\x00\x00\x00"
print("len=%d sync@0x%X start@0x%X cmd@0x%X stream-head=%s"
      % (len(buf), sync, start, cmd, " ".join("%02X" % b for b in buf[cmd:cmd + 9])))


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            return False
    time.sleep_ms(1); return True


def decode(s):
    return ("DONE=%d Busy=%d Fail=%d StdPreamble=%d BSE=%s ExecErr=%d IDErr=%d InvCmd=%d"
            % ((s >> 8) & 1, (s >> 12) & 1, (s >> 13) & 1, (s >> 21) & 1,
               BSE[(s >> 23) & 7], (s >> 26) & 1, (s >> 27) & 1, (s >> 28) & 1))


def go(hz):
    spi = SPI(0, baudrate=hz, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
              sck=Pin(2), mosi=Pin(3), miso=Pin(4))
    reset_fpga()
    csn(0)
    spi.write(memoryview(buf)[cmd:])        # 0x7A + bitstream, CONTINUOUS
    spi.write(b"\xFF" * 512)                 # wake-up clocks
    csn(1)
    time.sleep_ms(3)
    csn(0); spi.write(bytes([0x3C, 0, 0, 0])); d = spi.read(4); csn(1)
    st = (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]
    print("  %7d Hz  DONE=%d status=0x%08X %s" % (hz, done.value(), st, decode(st)))
    spi.deinit()


print("=== continuous 0x7A + bitstream ===")
for hz in (2_000_000, 1_000_000, 500_000):
    go(hz)
print("\nStdPreamble=1 => syncing. DONE=1 => configured (LEDs lit).")
