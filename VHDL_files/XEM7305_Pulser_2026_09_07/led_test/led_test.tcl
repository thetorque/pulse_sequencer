# led_test.tcl -- non-project headless build of the master-board LED test.
#   vivado -mode batch -source led_test.tcl   (run from this folder)
set here [file dirname [file normalize [info script]]]
cd $here
read_vhdl led_test.vhd
read_xdc  led_test.xdc
synth_design -top led_test -part xc7s50csga324-1
opt_design
place_design
route_design
write_bitstream -force led_test.bit
puts "== BITSTREAM: [file normalize led_test.bit] =="
