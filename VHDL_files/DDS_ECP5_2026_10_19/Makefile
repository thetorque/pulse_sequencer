# ECP5 DDS board -- Phase-1 LED bring-up
# Toolchain: oss-cad-suite (yosys + ghdl plugin, nextpnr-ecp5, ecppack, openFPGALoader)
#
#   make                  # build default TOP (led_static) -> .bit
#   make prog             # build + load to SRAM (volatile, fast iterate)
#   make TOP=led_blink prog
#   make flash            # write bitstream to flash via JTAG (persists) -- use when stable
#   make clean
#
# Override the JTAG probe if not using a Pico/DirtyJTAG:  make PROBE=ft2232 prog

TOP     ?= led_static
DEVICE  := --25k
PACKAGE := CABGA256
SPEED   := 6
PROBE   ?= dirtyJtag

# Per-design source lists (multi-file designs: leaf modules first, top last) and
# constraint files. Anything not listed falls back to single-file + dds_leds.lpf.
SRC_dds_top   := config_ram.vhd bus_rx.vhd ad9912_spi.vhd dac_spi.vhd sideband_spi.vhd dds_top.vhd
SRC_dac_test  := dac_spi.vhd dac_test.vhd
LPF_dds_top   := dds_ecp5.lpf
LPF_dac_test  := dac_test.lpf
LPF_led_chase := dds_chase.lpf

SRC := $(if $(SRC_$(TOP)),$(SRC_$(TOP)),$(TOP).vhd)
LPF ?= $(if $(LPF_$(TOP)),$(LPF_$(TOP)),dds_leds.lpf)

# GHDL (inside yosys) needs its library prefix. Derived from the ghdl binary
# location: <oss-cad-suite>/bin/ghdl -> <oss-cad-suite>/lib/ghdl. Override if needed.
GHDL_PREFIX ?= $(abspath $(dir $(shell command -v ghdl))/../lib/ghdl)
export GHDL_PREFIX

all: $(TOP).bit

$(TOP).json: $(SRC)
	yosys -m ghdl -p "ghdl --std=08 $(SRC) -e $(TOP); synth_ecp5 -top $(TOP) -json $@"

$(TOP).config: $(TOP).json $(LPF)
	nextpnr-ecp5 $(DEVICE) --package $(PACKAGE) --speed $(SPEED) \
	  --json $(TOP).json --lpf $(LPF) --textcfg $@

$(TOP).bit: $(TOP).config
	ecppack $(TOP).config $@

# Compressed bitstream for the Pico W Slave-SPI loader (fits MicroPython fs).
# ECP5 decompresses on-chip during config; works over SSPI the same as JTAG.
compress: $(TOP).config
	ecppack --compress $(TOP).config $(TOP)_c.bit
	@ls -l $(TOP)_c.bit

# Load to volatile config SRAM -- fast, non-destructive, lost on power cycle.
prog: $(TOP).bit
	openFPGALoader -c $(PROBE) $(TOP).bit

# Write to flash via JTAG -- persists across power cycles. Only once bitstream is stable.
flash: $(TOP).bit
	openFPGALoader -c $(PROBE) -f $(TOP).bit

clean:
	rm -f *.json *.config *.bit *_c.bit

.PHONY: all prog flash compress clean
