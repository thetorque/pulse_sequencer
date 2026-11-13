"""Configure the XEM7305 with bp_proto.bit (DDS bus protocol test: WRITE_ROWS + RESET + STEPNEXT loop)."""
import os, sys
import ok

bit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bp_proto.bit")
xem = ok.FrontPanel()
if xem.GetDeviceCount() < 1:
    sys.exit("No Opal Kelly devices found.")
serial = xem.GetDeviceListSerial(0)
xem.OpenBySerial(serial)
print(f"Connected to '{xem.GetDeviceID()}' (serial {serial})")
r = xem.ConfigureFPGA(bit)
if r:
    sys.exit(f"ConfigureFPGA failed: {r}")
print(f"Configured with {bit}")
