"""
Phase 1 bring-up smoke test for the XEM7305 pulser host-interface scaffold
(../src/photon.vhd). Exercises every endpoint address in the legacy map
and checks the fixed/echoed values the scaffold is expected to return.

This is standalone and does NOT reuse Python_files/servers/pulser/ok.py —
that module is compiled against the old XEM6010-era FrontPanel SDK and
won't work with the XEM7305. Point PYTHONPATH (or copy the module next
to this script) at the `ok` module bundled with your installed FrontPanel
SDK instead (FrontPanelUSB install dir, API/python subfolder).

Written against the FrontPanel 6 (FP6) Python API -- device enumeration
lives on a separate `ok.FrontPanelDevices()` object, and all wire/trigger/
pipe calls go through `GetFPGADataPortClassic()` rather than the device
object directly. See:
https://docs.opalkelly.com/fpsdk/fp6-migration-guide/python/
If your installed SDK is still FP5 (flat `ok.FrontPanel()` with
GetDeviceCount/SetWireInValue etc. directly on it), this script won't
match -- tell me and I'll revert to that style instead.

Usage:
    python smoke_test.py path/to/photon.bit

Requires Python 3 and the Opal Kelly `ok` FrontPanel Python module.
"""
import sys

import ok


PIPE_BLOCK_SIZE = 16  # bytes; matches the block size used elsewhere in this project's api.py


def connect(bit_path):
    devices = ok.FrontPanelDevices()
    count = devices.GetCount()
    if count < 1:
        sys.exit("No Opal Kelly devices found.")
    for i in range(count):
        print(f"  Found device, serial {devices.GetSerial(i)}")

    xem = devices.Open()
    if xem is None:
        sys.exit("Failed to open device.")

    info = ok.okTDeviceInfo()
    xem.GetDeviceInfo(info)
    print(f"Connected to device ID '{info.deviceID}' "
          f"(serial {info.serialNumber}, product {info.productName})")

    if xem.ConfigureFPGA(bit_path) != ok.ErrorCode.NoError:
        sys.exit(f"Failed to configure FPGA with {bit_path}")
    print(f"Configured FPGA with {bit_path}")

    if not xem.IsFrontPanelEnabled():
        sys.exit("Bitstream loaded but FrontPanel support is not enabled -- wrong .bit file?")

    dp = xem.GetFPGADataPortClassic()
    if dp is None:
        sys.exit("Failed to get FPGA data port.")
    return dp


def test_wire_in_leds(dp):
    print("\n--- WireIn 0x00 -> LEDs 0-2 ---")
    for bits in (0b001, 0b010, 0b100, 0b111, 0b000):
        dp.SetWireInValue(0x00, bits, 0x07)
        dp.UpdateWireIns()
        input(f"  Wrote WireIn 0x00 = {bits:#05b} -- check LEDs 0-2, press Enter to continue")


def test_wire_out_echo(dp):
    print("\n--- WireOut 0x21/0x22 echo check ---")
    dp.SetWireInValue(0x00, 0x5, 0x7)  # arbitrary known pattern on ep00wire
    dp.UpdateWireIns()
    dp.ActivateTriggerIn(0x40, 0)      # pulse a bit in ep40wire so it's nonzero-ish transiently

    dp.UpdateWireOuts()
    ep21 = dp.GetWireOutValue(0x21)
    ep22 = dp.GetWireOutValue(0x22)
    print(f"  WireOut 0x21 (should reflect WireIn 0x00) = {ep21:#010x}")
    print(f"  WireOut 0x22 (mirrors TriggerIn 0x40, a single-cycle pulse -- "
          f"expect this to read back as 0x00000000, that's normal, not a failure) = {ep22:#010x}")
    assert ep21 & 0x7 == 0x5, f"expected low 3 bits 0x5, got {ep21:#x}"
    print("  OK: WireOut 0x21 matches WireIn 0x00")


def test_pipe_out_patterns(dp):
    print("\n--- BTPipeOut fixed test patterns ---")
    expected = {0xA0: 0xA0A0A0A0, 0xA1: 0xA1A1A1A1, 0xA2: 0xA2A2A2A2}
    for addr, exp in expected.items():
        buf = bytearray(PIPE_BLOCK_SIZE)
        dp.ReadFromBlockPipeOut(addr, PIPE_BLOCK_SIZE, buf)
        got = int.from_bytes(buf[0:4], byteorder="little")
        status = "OK" if got == exp else "MISMATCH"
        print(f"  Pipe {addr:#04x}: expected {exp:#010x}, got {got:#010x}  [{status}]")


def test_pipe_in_writes(dp):
    print("\n--- BTPipeIn writes (0x80 pulse program, 0x81 DDS program) ---")
    dummy = bytearray(PIPE_BLOCK_SIZE)
    for addr in (0x80, 0x81):
        n = dp.WriteToBlockPipeIn(addr, PIPE_BLOCK_SIZE, dummy)
        status = "OK" if n == PIPE_BLOCK_SIZE else "UNEXPECTED RETURN"
        print(f"  Pipe {addr:#04x}: wrote {n} bytes  [{status}]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} path/to/photon.bit")

    dp = connect(sys.argv[1])
    test_wire_in_leds(dp)
    test_wire_out_echo(dp)
    test_pipe_out_patterns(dp)
    test_pipe_in_writes(dp)
    print("\nAll checks completed.")
