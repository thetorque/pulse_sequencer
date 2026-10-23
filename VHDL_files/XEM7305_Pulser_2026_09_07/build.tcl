# build.tcl -- headless synth -> impl -> bitstream for the XEM7305 pulser.
#
# Companion to create_project.tcl. Designed for remote/batch use:
#
#   vivado -mode batch -source build.tcl                 # incremental (open project, rebuild)
#   vivado -mode batch -source build.tcl -tclargs fresh  # recreate the project from scratch
#   vivado -mode batch -source build.tcl -tclargs clean  # reset the runs, then rebuild
#
# First run: no ./build project exists -> it sources create_project.tcl (slow,
# regenerates all IP incl. MIG). Later runs: it opens the existing project and
# re-synthesises only what changed (fast). Newly added src/*.vhd|*.v files are
# picked up automatically. Exits nonzero on any synth/impl failure, so an SSH
# caller can tell success from failure by the exit code.

# Run from this script's own directory, so every relative path (./build,
# ./src/ip, ./create_project.tcl) resolves exactly as create_project.tcl expects
# -- regardless of where Vivado was launched from.
cd [file dirname [file normalize [info script]]]

set PROJ_NAME "xem7305_pulser"
set PROJ_DIR  "./build"
set PROJ_XPR  "$PROJ_DIR/$PROJ_NAME.xpr"
set NJOBS     8

# ---- argument handling -----------------------------------------------------
set do_fresh 0
set do_clean 0
foreach a $argv {
  switch -- $a {
    fresh { set do_fresh 1 }
    clean { set do_clean 1 }
    default { puts "WARNING: ignoring unknown arg '$a'" }
  }
}

# ---- open or create the project -------------------------------------------
if {$do_fresh && [file exists $PROJ_DIR]} {
  puts "== fresh build requested: removing $PROJ_DIR =="
  file delete -force $PROJ_DIR
}

if {[file exists $PROJ_XPR]} {
  puts "== opening existing project $PROJ_XPR =="
  open_project $PROJ_XPR
  # keep the project in sync with any source files added since it was created
  add_files -quiet -norecurse [glob -nocomplain ./src/*.vhd ./src/*.v]
  set_property top photon [current_fileset]
  update_compile_order -fileset sources_1
} else {
  puts "== no project found: creating it via create_project.tcl =="
  source ./create_project.tcl
  open_project $PROJ_XPR
}

if {$do_clean} {
  puts "== clean build requested: resetting runs =="
  reset_run synth_1
}

# ---- synthesis -------------------------------------------------------------
puts "== launching synthesis =="
reset_run synth_1
launch_runs synth_1 -jobs $NJOBS
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
  puts "ERROR: synthesis did not complete (status: [get_property STATUS [get_runs synth_1]])"
  exit 1
}
puts "== synthesis complete =="

# ---- implementation + bitstream -------------------------------------------
puts "== launching implementation + write_bitstream =="
launch_runs impl_1 -to_step write_bitstream -jobs $NJOBS
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
  puts "ERROR: implementation did not complete (status: [get_property STATUS [get_runs impl_1]])"
  exit 1
}
puts "== implementation complete =="

# ---- reports (timing is load-bearing here: the DDR3 read path is placement-
#      marginal, so always surface WNS -- see README "read-path hardening") ---
open_run impl_1
set rptdir "$PROJ_DIR/reports"
file mkdir $rptdir
report_timing_summary -file $rptdir/timing_summary.rpt -quiet
report_utilization    -file $rptdir/utilization.rpt    -quiet
report_drc            -file $rptdir/drc.rpt             -quiet

# worst-case setup slack (guarded: a fully-constrained design always has paths)
set wns "n/a"
if {![catch {get_timing_paths -setup -max_paths 1 -nworst 1} paths] && [llength $paths] > 0} {
  set wns [get_property SLACK [lindex $paths 0]]
}
puts "== TIMING: setup WNS = $wns ns  (negative = failing timing) =="

# ---- locate + copy the bitstream to a predictable spot --------------------
set bits [glob -nocomplain $PROJ_DIR/*.runs/impl_1/*.bit]
if {[llength $bits] == 0} {
  puts "ERROR: no .bit produced"
  exit 1
}
set src_bit [lindex $bits 0]
set out_bit "$PROJ_DIR/photon.bit"
file copy -force $src_bit $out_bit
puts "== BITSTREAM: $out_bit =="
puts "== reports:   $rptdir/ =="
puts "== BUILD OK =="
exit 0
