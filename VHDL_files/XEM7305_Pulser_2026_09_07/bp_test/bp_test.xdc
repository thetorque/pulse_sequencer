# Master FPGA board: status LEDs D4..D11 + backplane lines (Bank 15, LVCMOS33).
# Balls from Opal Kelly XEM7305.csv.
set_property -dict { PACKAGE_PIN H15  IOSTANDARD LVCMOS33 } [get_ports {led_out[0]}]  ;# D4
set_property -dict { PACKAGE_PIN G15  IOSTANDARD LVCMOS33 } [get_ports {led_out[1]}]  ;# D5
set_property -dict { PACKAGE_PIN G16  IOSTANDARD LVCMOS33 } [get_ports {led_out[2]}]  ;# D6
set_property -dict { PACKAGE_PIN G17  IOSTANDARD LVCMOS33 } [get_ports {led_out[3]}]  ;# D7
set_property -dict { PACKAGE_PIN F13  IOSTANDARD LVCMOS33 } [get_ports {led_out[4]}]  ;# D8
set_property -dict { PACKAGE_PIN E13  IOSTANDARD LVCMOS33 } [get_ports {led_out[5]}]  ;# D9
set_property -dict { PACKAGE_PIN D18  IOSTANDARD LVCMOS33 } [get_ports {led_out[6]}]  ;# D10
set_property -dict { PACKAGE_PIN C18  IOSTANDARD LVCMOS33 } [get_ports {led_out[7]}]  ;# D11

set_property -dict { PACKAGE_PIN G13  IOSTANDARD LVCMOS33 } [get_ports {bp[0]}]  ;# BACKPLANE_SCK       MC1B_31 B15_IO_0
set_property -dict { PACKAGE_PIN K13  IOSTANDARD LVCMOS33 } [get_ports {bp[1]}]  ;# BACKPLANE_MOSI      MC1B_33 B15_IO_25
set_property -dict { PACKAGE_PIN B13  IOSTANDARD LVCMOS33 } [get_ports {bp[2]}]  ;# BACKPLANE_CS        MC1B_34 B15_L1P
set_property -dict { PACKAGE_PIN A13  IOSTANDARD LVCMOS33 } [get_ports {bp[3]}]  ;# BACKPLANE_STEPNEXT  MC1B_36 B15_L1N
set_property -dict { PACKAGE_PIN D12  IOSTANDARD LVCMOS33 } [get_ports {bp[4]}]  ;# BACKPLANE_RAMRESET  MC1B_23 B15_L5N
set_property -dict { PACKAGE_PIN B16  IOSTANDARD LVCMOS33 } [get_ports {bp[5]}]  ;# BACKPLANE_AUX1      MC1B_26 B15_L4P
set_property -dict { PACKAGE_PIN F14  IOSTANDARD LVCMOS33 } [get_ports {bp[6]}]  ;# BACKPLANE_AUX2      MC1B_27 B15_L13P_MRCC
set_property -dict { PACKAGE_PIN F15  IOSTANDARD LVCMOS33 } [get_ports {bp[7]}]  ;# BACKPLANE_AUX3      MC1B_29 B15_L13N_MRCC

set_property CFGBVS GND [current_design]
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS True [current_design]
