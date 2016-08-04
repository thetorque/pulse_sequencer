
# PlanAhead Launch Script for Pre-Synthesis Floorplanning, created by Project Navigator

create_project -name photon -dir "C:/Users/katori/Desktop/pulse_sequencer/VHDL_files/Pulser_w_2015_07_28/photon/planAhead_run_1" -part xc6slx45fgg484-2
set_param project.pinAheadLayout yes
set srcset [get_property srcset [current_run -impl]]
set_property target_constrs_file "xem6010.ucf" [current_fileset -constrset]
add_files [list {okCoreHarness.ngc}]
set hdlfile [add_files [list {readout_count_fifo.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
add_files [list {okWireOut.ngc}]
add_files [list {okWireIn.ngc}]
add_files [list {okTriggerIn.ngc}]
set hdlfile [add_files [list {okLibrary.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
add_files [list {okBTPipeOut.ngc}]
add_files [list {okBTPipeIn.ngc}]
set hdlfile [add_files [list {normal_pmt_fifo.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {ipcore_dir/pulse_fifo.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {ipcore_dir/pulser_ram.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {ipcore_dir/fifo_photon.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {ipcore_dir/clk_pll_100_in_200_out.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {dds_fifo.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set hdlfile [add_files [list {photon.vhd}]]
set_property file_type VHDL $hdlfile
set_property library work $hdlfile
set_property top photon $srcset
add_files [list {xem6010.ucf}] -fileset [get_property constrset [current_run]]
add_files [list {C:/Users/katori/Desktop/pulse_sequencer/VHDL_files/Pulser_w_2015_07_28/photon/pulser_ram.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/dds_fifo.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/fifo_photon.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/normal_pmt_fifo.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/pulser_ram.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/pulse_fifo.ncf}] -fileset [get_property constrset [current_run]]
add_files [list {ipcore_dir/readout_count_fifo.ncf}] -fileset [get_property constrset [current_run]]
open_rtl_design -part xc6slx45fgg484-2
