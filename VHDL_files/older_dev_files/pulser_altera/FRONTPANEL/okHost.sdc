############################################################################
# ZEM4310 - Quartus Constraints File
#
# Timing constraints for the ZEM4310.
#
# Copyright (c) 2004-2010 Opal Kelly Incorporated
# $Rev: 584 $ $Date: 2010-10-01 11:14:42 -0500 (Fri, 01 Oct 2010) $
############################################################################


#**************************************************************
# Time Information
#**************************************************************

set_time_format -unit ns -decimal_places 3



#**************************************************************
# Create Clock
#**************************************************************

create_clock -name {okUH[0]} -period 9.920 -waveform { 0.000 4.960 } [get_ports {okUH[0]}]
create_clock -name {virt_okUH0} -period 9.920 -waveform { 0.000 4.960 } 


#**************************************************************
# Create Generated Clock
#**************************************************************

create_generated_clock -name {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]} -source [get_pins {okHI|ok_altpll0|altpll_component|auto_generated|pll1|inclk[0]}] -duty_cycle 50.000 -multiply_by 1 -phase 0 -master_clock {okUH[0]} [get_pins {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] 


#**************************************************************
# Set Clock Uncertainty
#**************************************************************

set_clock_uncertainty -rise_from [get_clocks {virt_okUH0}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -setup 0.060  
set_clock_uncertainty -rise_from [get_clocks {virt_okUH0}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -hold 0.090  
set_clock_uncertainty -rise_from [get_clocks {virt_okUH0}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -setup 0.060  
set_clock_uncertainty -rise_from [get_clocks {virt_okUH0}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -hold 0.090  
set_clock_uncertainty -fall_from [get_clocks {virt_okUH0}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -setup 0.060  
set_clock_uncertainty -fall_from [get_clocks {virt_okUH0}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -hold 0.090  
set_clock_uncertainty -fall_from [get_clocks {virt_okUH0}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -setup 0.060  
set_clock_uncertainty -fall_from [get_clocks {virt_okUH0}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -hold 0.090  
set_clock_uncertainty -rise_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -rise_to [get_clocks {okUH[0]}]  0.010  
set_clock_uncertainty -rise_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -fall_to [get_clocks {okUH[0]}]  0.010  
set_clock_uncertainty -rise_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}]  0.020  
set_clock_uncertainty -rise_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}]  0.020  
set_clock_uncertainty -fall_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -rise_to [get_clocks {okUH[0]}]  0.010  
set_clock_uncertainty -fall_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -fall_to [get_clocks {okUH[0]}]  0.010  
set_clock_uncertainty -fall_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -rise_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}]  0.020  
set_clock_uncertainty -fall_from [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}] -fall_to [get_clocks {okHI|ok_altpll0|altpll_component|auto_generated|pll1|clk[0]}]  0.020  


#**************************************************************
# Set Input Delay
#**************************************************************
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUH[0]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  0.000 [get_ports {okUH[0]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUH[1]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  0.000 [get_ports {okUH[1]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUH[2]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  0.000 [get_ports {okUH[2]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUH[3]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  0.000 [get_ports {okUH[3]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUH[4]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  0.000 [get_ports {okUH[4]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[0]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[0]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[1]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[1]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[2]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[2]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[3]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[3]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[4]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[4]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[5]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[5]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[6]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[6]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[7]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[7]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[8]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[8]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[9]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[9]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[10]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[10]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[11]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[11]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[12]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[12]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[13]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[13]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[14]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[14]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[15]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[15]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[16]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[16]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[17]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[17]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[18]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[18]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[19]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[19]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[20]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[20]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[21]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[21]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[22]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[22]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[23]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[23]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[24]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[24]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[25]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[25]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[26]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[26]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[27]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[27]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[28]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[28]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[29]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[29]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[30]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[30]}]
set_input_delay -add_delay -max -clock [get_clocks {virt_okUH0}]  8.000 [get_ports {okUHU[31]}]
set_input_delay -add_delay -min -clock [get_clocks {virt_okUH0}]  2.000 [get_ports {okUHU[31]}]


#**************************************************************
# Set Output Delay
#**************************************************************

set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[0]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[0]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[1]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[1]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[2]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[2]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[3]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[3]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[4]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[4]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[5]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[5]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[6]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[6]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[7]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[7]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[8]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[8]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[9]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[9]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[10]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[10]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[11]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[11]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[12]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[12]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[13]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[13]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[14]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[14]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[15]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[15]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[16]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[16]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[17]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[17]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[18]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[18]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[19]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[19]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[20]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[20]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[21]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[21]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[22]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[22]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[23]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[23]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[24]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[24]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[25]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[25]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[26]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[26]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[27]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[27]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[28]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[28]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[29]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[29]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[30]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[30]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okUHU[31]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okUHU[31]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okHU[2]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okHU[2]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okHU[1]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okHU[1]}]
set_output_delay -add_delay -max -clock [get_clocks {okUH[0]}]  2.000 [get_ports {okHU[0]}]
set_output_delay -add_delay -min -clock [get_clocks {okUH[0]}]  -0.500 [get_ports {okHU[0]}]

# (C) 2001-2012 Altera Corporation. All rights reserved.
# Your use of Altera Corporation's design tools, logic functions and other 
# software and tools, and its AMPP partner logic functions, and any output 
# files any of the foregoing (including device programming or simulation 
# files), and any associated documentation or information are expressly subject 
# to the terms and conditions of the Altera Program License Subscription 
# Agreement, Altera MegaCore Function License Agreement, or other applicable 
# license agreement, including, without limitation, that your use is for the 
# sole purpose of programming logic devices manufactured by Altera and sold by 
# Altera or its authorized distributors.  Please refer to the applicable 
# agreement for further details.


# +---------------------------------------------------
# | Cut the async clear paths
# +---------------------------------------------------
set_false_path -to [get_pins -compatibility_mode -nocase *|alt_rst_sync_uq1|altera_reset_synchronizer_int_chain*|aclr]
set_false_path -to [get_pins -compatibility_mode -nocase *|alt_rst_sync_uq1|altera_reset_synchronizer_int_chain*|clrn]
