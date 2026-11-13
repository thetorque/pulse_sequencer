"""Configure the XEM7305 with bp_fast.bit (backplane SPEED test: PRBS7 frames on SCK/MOSI/CS/STEPNEXT)."""
import os, sys
import ok

bit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bp_fast.bit")
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
