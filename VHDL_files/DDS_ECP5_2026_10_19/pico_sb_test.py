# pico_sb_test.py -- test the ECP5 sideband SPI slave from the Pico W (SPI1 master).
# Load sideband_test into the ECP5 first, then run this.
# Expect the slave to return SIGNATURE 0xA5, then an echo of each previous byte.
#
# Pico SPI1: SCK=GP10, MOSI=GP11, MISO=GP12, CS=GP13 (manual), ATTN=GP9 (in).

from machine import Pin, SPI

spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
          sck=Pin(10), mosi=Pin(11), miso=Pin(12))
cs   = Pin(13, Pin.OUT, value=1)
attn = Pin(9, Pin.IN)


def hx(b):
    return " ".join("%02X" % x for x in b)


tx = bytes([0x3C, 0x81, 0x55, 0xF0])
rx = bytearray(len(tx))
cs(0)
spi.write_readinto(tx, rx)
cs(1)

print("TX  =", hx(tx))
print("RX  =", hx(rx))
print("ATTN=", attn.value())

exp = bytes([0xA5, 0x3C, 0x81, 0x55])     # SIG, echo 3C, echo 81, echo 55
if rx == exp:
    print("PASS: sideband SPI slave echo OK (last byte 0x%02X on LEDs)" % tx[-1])
else:
    print("FAIL: expected", hx(exp))
