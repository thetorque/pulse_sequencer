# bp_test.tcl -- non-project headless build of the master-board LED test.
#   vivado -mode batch -source bp_test.tcl   (run from this folder)
set here [file dirname [file normalize [info script]]]
cd $here
read_vhdl bp_test.vhd
read_xdc  bp_test.xdc
synth_design -top bp_test -part xc7s50csga324-1
opt_design
place_design
route_design
write_bitstream -force bp_test.bit
puts "== BITSTREAM: [file normalize bp_test.bit] =="
