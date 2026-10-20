# pico_sspi_flow.py -- full documented ECP5 Slave-SPI programming flow, with each
# command in its OWN CS cycle:
#   READ_ID -> ISC_ENABLE(0xC6) -> LSC_BITSTREAM_BURST(0x7A)+bitstream -> ISC_DISABLE(0x26)
# Burst+data is one continuous transaction (0x7A placed just before the preamble).

from machine import Pin, SPI
import time, os

BITFILE = "led_half_c.bit"     # distinctive: only D1-D3 green when configured

csn      = Pin(5, Pin.OUT, value=1)
programn = Pin(6, Pin.OUT, value=1)
initn    = Pin(7, Pin.IN, Pin.PULL_UP)
done     = Pin(8, Pin.IN, Pin.PULL_UP)
spi = SPI(0, baudrate=1_000_000, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
          sck=Pin(2), mosi=Pin(3), miso=Pin(4))

BSE = {0: "none", 1: "ID", 2: "CMD", 3: "CRC", 4: "PRMB", 5: "ABRT", 6: "OVFL", 7: "SDM"}

_sz = os.stat(BITFILE)[6]
buf = bytearray(_sz)
with open(BITFILE, "rb") as f:
    f.readinto(buf)
sync = buf.find(b"\xbd\xb3")
start = sync
while start > 0 and buf[start - 1] == 0xFF:
    start -= 1
cmd = start - 4
buf[cmd:start] = b"\x7A\x00\x00\x00"


def reset_fpga():
    programn(0); time.sleep_ms(2); programn(1)
    t0 = time.ticks_ms()
    while initn.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > 500:
            return False
    time.sleep_ms(1); return True


def command(opcode, operand=b"\x00\x00\x00"):      # single command, own CS
    csn(0); spi.write(bytes([opcode]) + operand); csn(1)


def rd(opcode):                                    # read command -> 32-bit
    csn(0); spi.write(bytes([opcode, 0, 0, 0])); d = spi.read(4); csn(1)
    return (d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]


def decode(s):
    return ("DONE=%d Busy=%d Fail=%d StdPreamble=%d BSE=%s ExecErr=%d IDErr=%d InvCmd=%d"
            % ((s >> 8) & 1, (s >> 12) & 1, (s >> 13) & 1, (s >> 21) & 1,
               BSE[(s >> 23) & 7], (s >> 26) & 1, (s >> 27) & 1, (s >> 28) & 1))


print("=== full SSPI programming flow ===")
reset_fpga()
print("ID        = 0x%08X" % rd(0xE0))

command(0xC6)                 # ISC_ENABLE
time.sleep_ms(1)
print("after EN  :", decode(rd(0x3C)))

command(0x0E)                 # ISC_ERASE (clear SRAM)
time.sleep_ms(10)
print("after ERA :", decode(rd(0x3C)))

csn(0)                        # LSC_BITSTREAM_BURST + bitstream, continuous
spi.write(memoryview(buf)[cmd:])
spi.write(b"\xFF" * 512)
csn(1)
time.sleep_ms(5)
print("after BURST:", decode(rd(0x3C)))

command(0x26)                 # ISC_DISABLE
time.sleep_ms(1)
st = rd(0x3C)
print("after DIS :", decode(st))
print("DONE pin  = %d  %s" % (done.value(), "SUCCESS" if done.value() else "fail"))
