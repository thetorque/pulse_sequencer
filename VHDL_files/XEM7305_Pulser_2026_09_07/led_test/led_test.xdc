# Master FPGA board status LEDs D4..D11 (Bank 15, LVCMOS33, active-high, 4k7 series).
# Balls from Opal Kelly XEM7305.csv (MC1 pin -> FPGA pin).
set_property -dict { PACKAGE_PIN H15  IOSTANDARD LVCMOS33 } [get_ports {led_out[0]}]  ;# MC1A_23  B15_L18P  D4
set_property -dict { PACKAGE_PIN G15  IOSTANDARD LVCMOS33 } [get_ports {led_out[1]}]  ;# MC1A_25  B15_L18N  D5
set_property -dict { PACKAGE_PIN G16  IOSTANDARD LVCMOS33 } [get_ports {led_out[2]}]  ;# MC1A_27  B15_L14P  D6
set_property -dict { PACKAGE_PIN G17  IOSTANDARD LVCMOS33 } [get_ports {led_out[3]}]  ;# MC1A_29  B15_L14N  D7
set_property -dict { PACKAGE_PIN F13  IOSTANDARD LVCMOS33 } [get_ports {led_out[4]}]  ;# MC1A_31  B15_L17P  D8
set_property -dict { PACKAGE_PIN E13  IOSTANDARD LVCMOS33 } [get_ports {led_out[5]}]  ;# MC1A_33  B15_L17N  D9
set_property -dict { PACKAGE_PIN D18  IOSTANDARD LVCMOS33 } [get_ports {led_out[6]}]  ;# MC1A_35  B15_L11P  D10
set_property -dict { PACKAGE_PIN C18  IOSTANDARD LVCMOS33 } [get_ports {led_out[7]}]  ;# MC1A_37  B15_L11N  D11

set_property CFGBVS GND [current_design]
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS True [current_design]
