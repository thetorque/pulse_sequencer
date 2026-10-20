# pico_sspi_fix.py -- strip the ASCII comment header, then 0x7A burst + bitstream.
# The ecppack .bit begins with "...Part: LFE5U-25F-6CABGA256\0" BEFORE the
# 0xFFFF...BDB3 preamble. We stream from the 0xFF padding+preamble onward.

from machine import Pin, SPI
import time

BITFILE = "led_static_c.bit"

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)
spi = SPI(0, baudrate=1_000_000, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
          sck=Pin(2), mosi=Pin(3), miso=Pin(4))

BSE = {0: "none", 1: "ID", 2: "CMD", 3: "CRC", 4: "PRMB", 5: "ABRT", 6: "OVFL", 7: "SDM"}

with open(BITFILE, "rb") as f:
    RAW = f.read()

# strip comment header: find 0xBDB3 sync, back up over the 0xFF padding run
sync = RAW.find(b"\xbd\xb3")
start = sync
while start > 0 and RAW[start - 1] == 0xFF:
    start -= 1
PAY = memoryview(RAW)[start:]          # zero-copy slice (Pico RAM is tight)
print("raw=%d  sync@0x%X  stripped start@0x%X  payload=%d  first=%s"
      % (len(RAW), sync, start, len(PAY), " ".join("%02X" % b for b in bytes(PAY[:6]))))


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            return False
    time.sleep_ms(1); return True


def rd_status():
    csn(0); spi.write(bytes([0x3C, 0, 0, 0])); d = spi.read(4); csn(1)
    return (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]


def decode(s):
    return ("DONE=%d Busy=%d Fail=%d StdPreamble=%d BSE=%s ExecErr=%d IDErr=%d InvCmd=%d"
            % ((s >> 8) & 1, (s >> 12) & 1, (s >> 13) & 1, (s >> 21) & 1,
               BSE[(s >> 23) & 7], (s >> 26) & 1, (s >> 27) & 1, (s >> 28) & 1))


def attempt(label, burst, payload):
    reset_fpga()
    csn(0)
    if burst:
        spi.write(bytes([0x7A, 0, 0, 0]))
    spi.write(payload)
    spi.write(b"\xFF" * 256)
    csn(1)
    time.sleep_ms(3)
    st = rd_status()
    print("  %-22s DONE=%d status=0x%08X %s" % (label, done.value(), st, decode(st)))


attempt("0x7A + stripped", True, PAY)
attempt("raw stripped (no 7A)", False, PAY)
print("\nIf DONE=1 -> LEDs should be lit. If StdPreamble=1 now, we are syncing.")
