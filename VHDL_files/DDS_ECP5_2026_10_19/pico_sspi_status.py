# pico_sspi_status.py -- stream the bitstream and DECODE the ECP5 status register.
# Tells us whether the device saw the preamble (bit21), hit a CRC/CMD error, etc.
# Streams the WHOLE file in one SPI write (no chunk gaps) at a LOW clock, both with
# and without the 0x7A burst command.

from machine import Pin, SPI
import time

BITFILE = "led_static_c.bit"
SPEEDS  = (1_000_000, 500_000)

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)

BSE = {0: "none", 1: "ID", 2: "CMD", 3: "CRC", 4: "PRMB", 5: "ABRT", 6: "OVFL", 7: "SDM"}

# load the whole bitstream into RAM once
with open(BITFILE, "rb") as f:
    BITS = f.read()
print("bitstream %d bytes in RAM" % len(BITS))


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            return False
    time.sleep_ms(1); return True


def rd_status(spi):
    csn(0); spi.write(bytes([0x3C, 0, 0, 0])); d = spi.read(4); csn(1)
    return (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]


def rd_id(spi):
    csn(0); spi.write(bytes([0xE0, 0, 0, 0])); d = spi.read(4); csn(1)
    return (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]


def decode(s):
    return ("DONE=%d Busy=%d Fail=%d StdPreamble=%d BSE=%s ExecErr=%d IDErr=%d InvCmd=%d"
            % ((s >> 8) & 1, (s >> 12) & 1, (s >> 13) & 1, (s >> 21) & 1,
               BSE[(s >> 23) & 7], (s >> 26) & 1, (s >> 27) & 1, (s >> 28) & 1))


def attempt(spi, label, burst):
    reset_fpga()
    csn(0)
    if burst:
        spi.write(bytes([0x7A, 0, 0, 0]))
    spi.write(BITS)
    spi.write(b"\xFF" * 256)
    csn(1)
    time.sleep_ms(3)
    st = rd_status(spi)
    print("  %-16s DONE=%d  status=0x%08X  %s" % (label, done.value(), st, decode(st)))


for hz in SPEEDS:
    spi = SPI(0, baudrate=hz, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
              sck=Pin(2), mosi=Pin(3), miso=Pin(4))
    print("\n== %d Hz ==  (link check ID=0x%08X)" % (hz, rd_id(spi)))
    attempt(spi, "raw stream", False)
    attempt(spi, "0x7A + stream", True)
    spi.deinit()
