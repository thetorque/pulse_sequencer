# bp_proto.tcl -- non-project headless build of the master-side DDS bus protocol test sender.
#   vivado -mode batch -source bp_proto.tcl   (run from this folder)
set here [file dirname [file normalize [info script]]]
cd $here
read_vhdl bp_proto.vhd
read_xdc  bp_proto.xdc
synth_design -top bp_proto -part xc7s50csga324-1
opt_design
place_design
route_design
report_timing_summary -max_paths 1 -no_header -file timing.txt
puts "== WNS: [get_property SLACK [get_timing_paths -max_paths 1 -setup]] ns =="
write_bitstream -force bp_proto.bit
puts "== BITSTREAM: [file normalize bp_proto.bit] =="
