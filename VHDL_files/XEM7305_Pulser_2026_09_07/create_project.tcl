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

# Phase 2/6: Clocking Wizard (MMCM) IP, replacing the legacy design's
# clk_pll_100_in_200_out. Same three output frequencies (200/100/20 MHz)
# and roles (PMT oversampling / main state machine / DDS+line-trigger).
#
# Phase 6 (DDR3 migration) re-sources this from MIG's ui_clk instead of
# the XEM7305's raw 200 MHz sys_clk: MIG (src/ip/ddr3_256_16) now owns
# the physical sys_clk_p/sys_clk_n differential pins directly (its
# System Clock config is Differential, matching the proven
# Locally_compiled_ramtester reference -- see AR#45588 on why System
# Clock=No Buffer + a separate IBUFGDS couldn't be validated instead).
# ui_clk = 200 MHz * CLKFBOUT_MULT(13) / DIVCLK_DIVIDE(2) / CLKOUT3_DIVIDE(16)
#        = 81.25 MHz exactly (confirmed from ddr3_256_16_mig.vhd's generics).
# PRIM_SOURCE is No_buffer (not Single_ended_clock_capable_pin) because
# ui_clk is an already-BUFG'd internal fabric net from MIG, not a raw
# external pin -- clk_wiz_0 must not add its own IBUF/pin buffer for it.
# 81.25 MHz doesn't divide the MMCM's 0.125-step multiply grid evenly
# back into exact 200/100/20 MHz (the /2/16 factors reintroduce a /13
# that doesn't fit within CLKFBOUT_MULT_F's <=64 limit), so expect a
# small (sub-0.1%, likely sub-0.01%) output frequency error -- check
# the actual vs. requested frequencies Vivado reports after generating.
create_ip -name clk_wiz -vendor xilinx.com -library ip -module_name clk_wiz_0 -dir ./src/ip
set_property -dict [list \
    CONFIG.PRIM_IN_FREQ {81.250} \
    CONFIG.PRIM_SOURCE {No_buffer} \
    CONFIG.CLKOUT1_USED {true} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {200.000} \
    CONFIG.CLKOUT2_USED {true} \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {100.000} \
    CONFIG.CLKOUT3_USED {true} \
    CONFIG.CLKOUT3_REQUESTED_OUT_FREQ {20.000} \
    CONFIG.NUM_OUT_CLKS {3} \
    CONFIG.USE_LOCKED {true} \
    CONFIG.USE_RESET {false} \
] [get_ips clk_wiz_0]
generate_target {instantiation_template synthesis simulation} [get_files ./src/ip/clk_wiz_0/clk_wiz_0.xci]

add_files -norecurse [glob ./src/*.vhd ./src/*.v]
set_property top photon [current_fileset]

add_files -fileset constrs_1 -norecurse ./constraints/xem7305.xdc

update_compile_order -fileset sources_1

puts "Project created at $PROJ_DIR/$PROJ_NAME.xpr — open in Vivado GUI or run synth_design/impl_design/write_bitstream from here."
