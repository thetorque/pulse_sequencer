# pico_sspi_load.py -- WORKING ECP5 Slave-SPI loader for the on-board Pico W.
# Configures the ECP5 SRAM over the board's config port.  Verified 2026-10-20.
#
# Flow (TN-02039, each command in its own CS cycle; burst+data continuous):
#   PROGRAMN pulse -> INITN high
#   ISC_ENABLE (0xC6) -> ISC_ERASE (0x0E) -> LSC_BITSTREAM_BURST (0x7A)+bitstream
#   -> ISC_DISABLE (0x26) -> DONE pin high
#
# The ecppack .bit begins with an ASCII comment header before the 0xFFFF..BDB3
# preamble; we place the 0x7A command in the 4 bytes just before the preamble and
# stream from there, so burst+bitstream is ONE continuous SPI transaction.
#
# Pins (verified against the DDS netlist):
#   GP2=SCK->CCLK  GP3=MOSI->D0  GP4=MISO<-D1  GP5=CSn->SN
#   GP6=PROGRAMN   GP7=INITN(in) GP8=DONE(in)
#
# Usage:
#   mpremote cp led_half_c.bit :led_half_c.bit
#   mpremote run pico_sspi_load.py

from machine import Pin, SPI
import time, os

BITFILE = "led_chase_c.bit"    # compressed bitstream (ecppack --compress); set to led_half_c.bit etc. to swap patterns
SPI_HZ  = 2_000_000

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)
spi = SPI(0, baudrate=SPI_HZ, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
          sck=Pin(2), mosi=Pin(3), miso=Pin(4))


def _load_buffer():
    sz = os.stat(BITFILE)[6]
    buf = bytearray(sz)                 # single buffer (Pico RAM is tight)
    with open(BITFILE, "rb") as f:
        f.readinto(buf)
    sync = buf.find(b"\xbd\xb3")        # locate 0xBDB3 preamble
    start = sync
    while start > 0 and buf[start - 1] == 0xFF:
        start -= 1                      # back up over the 0xFF padding
    cmd = start - 4
    buf[cmd:start] = b"\x7A\x00\x00\x00"   # LSC_BITSTREAM_BURST, immediately before preamble
    return buf, cmd


def _reset():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            raise RuntimeError("INITN never went high (check rails / PROGRAMN)")
    time.sleep_ms(1)


def _cmd(opcode):
    csn(0); spi.write(bytes([opcode, 0, 0, 0])); csn(1)


def _rd(opcode):
    csn(0); spi.write(bytes([opcode, 0, 0, 0])); d = spi.read(4); csn(1)
    return (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]


def program():
    buf, cmd = _load_buffer()
    _reset()
    idc = _rd(0xE0)
    print("READ_ID = 0x%08X %s" % (idc, "(LFE5U-25 OK)" if idc == 0x41111043 else "(??)"))

    _cmd(0xC6); time.sleep_ms(1)          # ISC_ENABLE
    _cmd(0x0E); time.sleep_ms(10)         # ISC_ERASE (clear config SRAM)

    csn(0)                                 # BITSTREAM_BURST + bitstream, continuous
    spi.write(memoryview(buf)[cmd:])
    spi.write(b"\xFF" * 512)               # wake-up clocks
    csn(1)
    time.sleep_ms(5)

    _cmd(0x26)                             # ISC_DISABLE -> user mode
    time.sleep_ms(1)

    d = done.value()
    print("DONE = %d  -> %s" % (d, "SUCCESS (bitstream running)" if d else "FAIL"))
    return d


if __name__ == "__main__":
    try:
        program()
    except Exception as e:
        print("ERROR:", e)
