# Backplane speed test, master side. 200 MHz LVDS system clock + LEDs D4..D11 + backplane.
set_property -dict { PACKAGE_PIN R2  IOSTANDARD LVDS_25 } [get_ports {sys_clk_p}]
set_property -dict { PACKAGE_PIN R1  IOSTANDARD LVDS_25 } [get_ports {sys_clk_n}]
set_property DIFF_TERM FALSE [get_ports {sys_clk_p}]
create_clock -name sys_clk -period 5.000 [get_ports {sys_clk_p}]

set_property -dict { PACKAGE_PIN H15  IOSTANDARD LVCMOS33 } [get_ports {led_out[0]}]  ;# D4
set_property -dict { PACKAGE_PIN G15  IOSTANDARD LVCMOS33 } [get_ports {led_out[1]}]  ;# D5
set_property -dict { PACKAGE_PIN G16  IOSTANDARD LVCMOS33 } [get_ports {led_out[2]}]  ;# D6
set_property -dict { PACKAGE_PIN G17  IOSTANDARD LVCMOS33 } [get_ports {led_out[3]}]  ;# D7
set_property -dict { PACKAGE_PIN F13  IOSTANDARD LVCMOS33 } [get_ports {led_out[4]}]  ;# D8
set_property -dict { PACKAGE_PIN E13  IOSTANDARD LVCMOS33 } [get_ports {led_out[5]}]  ;# D9
set_property -dict { PACKAGE_PIN D18  IOSTANDARD LVCMOS33 } [get_ports {led_out[6]}]  ;# D10
set_property -dict { PACKAGE_PIN C18  IOSTANDARD LVCMOS33 } [get_ports {led_out[7]}]  ;# D11

set_property -dict { PACKAGE_PIN G13  IOSTANDARD LVCMOS33 } [get_ports {bp[0]}]  ;# BACKPLANE_SCK
set_property -dict { PACKAGE_PIN K13  IOSTANDARD LVCMOS33 } [get_ports {bp[1]}]  ;# BACKPLANE_MOSI
set_property -dict { PACKAGE_PIN B13  IOSTANDARD LVCMOS33 } [get_ports {bp[2]}]  ;# BACKPLANE_CS
set_property -dict { PACKAGE_PIN A13  IOSTANDARD LVCMOS33 } [get_ports {bp[3]}]  ;# BACKPLANE_STEPNEXT
set_property -dict { PACKAGE_PIN D12  IOSTANDARD LVCMOS33 } [get_ports {bp[4]}]  ;# BACKPLANE_RAMRESET
set_property -dict { PACKAGE_PIN B16  IOSTANDARD LVCMOS33 } [get_ports {bp[5]}]  ;# BACKPLANE_AUX1
set_property -dict { PACKAGE_PIN F14  IOSTANDARD LVCMOS33 } [get_ports {bp[6]}]  ;# BACKPLANE_AUX2
set_property -dict { PACKAGE_PIN F15  IOSTANDARD LVCMOS33 } [get_ports {bp[7]}]  ;# BACKPLANE_AUX3
# fast-ish edges on the 4 used bus lines
set_property -dict { SLEW FAST DRIVE 8 } [get_ports {bp[0] bp[1] bp[2] bp[3]}]

set_property CFGBVS GND [current_design]
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS True [current_design]
