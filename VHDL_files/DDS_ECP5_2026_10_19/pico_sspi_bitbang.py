# pico_sspi_bitbang.py -- decisive HW-vs-SW test.
# Bit-bangs the ECP5 Slave-SPI READ_ID using PLAIN GPIO (no machine.SPI peripheral),
# on the same pins. Mode 0: MOSI set while SCK low, MISO sampled on SCK rising edge.
#
#   Bit-banged ID = 0x41111043  -> HARDWARE IS FINE; machine.SPI wasn't driving (software).
#   Bit-banged ID = 0x00000000  -> genuine continuity problem on SCK/MOSI/MISO/CS.
#
# Pins: GP2=SCK GP3=MOSI GP4=MISO GP5=CSn GP6=PROGRAMN GP7=INITN GP8=DONE

from machine import Pin
import time

sck  = Pin(2, Pin.OUT, value=0)
mosi = Pin(3, Pin.OUT, value=0)
miso = Pin(4, Pin.IN)
csn  = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            print("  !! INITN never high"); return False
    time.sleep_ms(1)
    return True


def xfer(b):
    r = 0
    for i in range(8):
        mosi.value((b >> (7 - i)) & 1)
        sck.value(1)
        r = (r << 1) | miso.value()
        sck.value(0)
    return r


def hx(b):
    return " ".join("%02X" % x for x in b)


print("=== bit-banged SSPI READ_ID (plain GPIO) ===")
reset_fpga()
print("INITN=%d DONE=%d" % (initn.value(), done.value()))

# Pin-drive sanity: toggle MOSI/SCK/CS so they are provably moving (measure if desired)
for _ in range(3):
    for p in (sck, mosi, csn):
        p.value(1); p.value(0)

for name, op in (("READ_ID 0xE0", 0xE0), ("READ_STATUS 0x3C", 0x3C)):
    tx = [op] + [0] * 8
    csn(0)
    rx = [xfer(x) for x in tx]
    csn(1)
    print("%-16s RX = %s" % (name, hx(rx)))

print("\nLook for  41 11 10 43  in the READ_ID RX.")
print("Present -> wiring OK, machine.SPI was the issue (we switch to bit-bang).")
print("All zero -> continuity fault on SCK(GP2/R30)/MOSI(GP3)/MISO(GP4)/CS(GP5).")
