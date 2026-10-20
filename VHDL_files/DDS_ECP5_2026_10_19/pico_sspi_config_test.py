# pico_sspi_config_test.py -- find the working ECP5 Slave-SPI config method.
# The link is proven (READ_ID=0x41111043). The ecppack .bit is a STAND-ALONE
# bitstream (sync 0xFFFFBDB3 + embedded commands), so the documented method is to
# just stream it raw. This tries a few candidates and stops at the first DONE=1.
#
# Pins: GP2=SCK GP3=MOSI GP4=MISO GP5=CSn GP6=PROGRAMN GP7=INITN GP8=DONE

from machine import Pin, SPI
import time

BITFILE = "led_static_c.bit"

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)
spi = SPI(0, baudrate=8_000_000, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
          sck=Pin(2), mosi=Pin(3), miso=Pin(4))


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            return False
    time.sleep_ms(1)
    return True


def stream_bitfile():
    with open(BITFILE, "rb") as f:
        buf = bytearray(4096)
        n = f.readinto(buf)
        while n:
            spi.write(buf[:n] if n < len(buf) else buf)
            n = f.readinto(buf)


def try_method(name, prefix=b"", suffix=b"", trailing=256):
    reset_fpga()
    csn(0)
    if prefix:
        spi.write(prefix)
    stream_bitfile()
    if suffix:
        spi.write(suffix)
    spi.write(b"\xFF" * trailing)     # wake-up clocks
    csn(1)
    time.sleep_ms(3)
    d = done.value()
    print("  [%-18s] DONE=%d %s" % (name, d, "<-- SUCCESS" if d else ""))
    return d


print("=== ECP5 SSPI config method search ===")
methods = [
    ("raw stream",        b"",                       b""),
    ("0x7A + stream",     b"\x7A\x00\x00\x00",       b""),
    ("ISC_EN + raw",      b"\xC6\x00\x00\x00",       b"\x26\x00\x00\x00"),
    ("ISC_EN+0x7A+raw",   b"\xC6\x00\x00\x00\x7A\x00\x00\x00", b"\x26\x00\x00\x00"),
]
for name, pre, suf in methods:
    if try_method(name, pre, suf):
        print("\nWINNER:", name, "-- LEDs should be lit. Keeping this config.")
        break
else:
    print("\nNone configured. Report which (if any) got closest.")
