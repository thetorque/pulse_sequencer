# create_project.tcl
#
# Recreates the Vivado project for the XEM7305 pulse-sequencer port from
# checked-in sources. Run from within this directory:
#
#   vivado -mode batch -source create_project.tcl
#
# Part: xc7s50csga324-1, matching Locally_compiled_ramtester (../XEM7305_references)
# and the "Device:" comment embedded in the encrypted OK IP netlists copied
# into src/ (e.g. src/okWireIn.v). Locally_compiled_photon_2026 targeted
# csga324-2 instead — confirm which speed grade your actual XEM7305 board
# uses before building for hardware; change PART below if -2 is correct.

set PART "xc7s50csga324-1"
set PROJ_NAME "xem7305_pulser"
set PROJ_DIR  "./build"

create_project $PROJ_NAME $PROJ_DIR -part $PART -force
set_property target_language VHDL [current_project]

add_files -norecurse [glob ./src/*.vhd ./src/*.v]
set_property top photon [current_fileset]

add_files -fileset constrs_1 -norecurse ./constraints/xem7305.xdc

update_compile_order -fileset sources_1

puts "Project created at $PROJ_DIR/$PROJ_NAME.xpr — open in Vivado GUI or run synth_design/impl_design/write_bitstream from here."
