# pico_sspi_diag.py -- ECP5 Slave-SPI link diagnostic (run via: mpremote run pico_sspi_diag.py)
# Does NOT program anything. It resets the ECP5, then probes READ_ID / READ_STATUS
# with a FULL-DUPLEX exchange and prints every returned byte, so we can see the
# IDCODE (0x41111043 for LFE5U-25) at whatever offset -- and whether MISO returns
# anything at all. Tries both SPI mode 0 and mode 3, at a slow clock.
#
# Pins (verified against the DDS netlist):
#   GP2=SCK->CCLK(N9)  GP3=MOSI->D0(T8)  GP4=MISO<-D1(T7)  GP5=CSn->SN(R8)
#   GP6=PROGRAMN  GP7=INITN(in)  GP8=DONE(in)

from machine import Pin, SPI
import time

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            print("  !! INITN never went high"); return False
    time.sleep_ms(1)
    return True


def hx(b):
    return " ".join("%02X" % x for x in b)


def probe(mode, hz):
    pol = 1 if mode == 3 else 0
    pha = 1 if mode == 3 else 0
    spi = SPI(0, baudrate=hz, polarity=pol, phase=pha, bits=8, firstbit=SPI.MSB,
              sck=Pin(2), mosi=Pin(3), miso=Pin(4))
    print("\n== SPI mode %d @ %d Hz ==" % (mode, hz))
    reset_fpga()
    print("  INITN=%d DONE=%d (after reset)" % (initn.value(), done.value()))

    # READ_ID (0xE0): send opcode + many trailing bytes, capture full duplex.
    for opname, op in (("READ_ID 0xE0", 0xE0), ("READ_STATUS 0x3C", 0x3C)):
        tx = bytes([op]) + b"\x00" * 8          # opcode + 8 capture bytes
        rx = bytearray(len(tx))
        csn(0)
        spi.write_readinto(tx, rx)
        csn(1)
        print("  %-16s TX=%s" % (opname, hx(tx)))
        print("  %-16s RX=%s" % ("", hx(rx)))
    spi.deinit()


print("=== ECP5 SSPI link diagnostic ===")
for mode in (0, 3):
    probe(mode, 1_000_000)
print("\nExpected somewhere in a READ_ID RX: 41 11 10 43  (LFE5U-25 IDCODE)")
print("All-zero RX in BOTH modes => MISO/clock not getting through (hardware/continuity).")
print("Nonzero/ID visible => link OK, we just fix the byte offset in the loader.")
