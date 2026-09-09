#!/usr/bin/env bash
# Phase 6c milestone 1 -- simulate the DDR3 line streamer with GHDL.
#
#   ./run_sim.sh
#
# Override the GHDL binary / library prefix via environment if your install
# needs it (e.g. the macOS "duplicate LC_RPATH" dyld-abort workaround: run a
# copy of libexec/ghdl with the extra rpaths stripped + re-signed, and point
# GHDL_PREFIX at <oss-cad-suite>/lib/ghdl):
#
#   GHDL=/tmp/ghdl_fixed \
#   GHDL_PREFIX=<oss-cad-suite>/lib/ghdl \
#   DYLD_LIBRARY_PATH=<oss-cad-suite>/lib \
#   ./run_sim.sh
#
# Vivado users can instead compile these four files into a work library and
# simulate tb_line_streamer in xsim.
# NB: no `set -e` -- some GHDL builds (notably oss-cad-suite on recent macOS)
# return a non-zero exit at process teardown even on success, which would
# otherwise abort the script between the analyze and run steps.
GHDL="${GHDL:-ghdl}"
cd "$(dirname "$0")"

SRCS="line_fifo_128x64.vhd mig_read_model.vhd ddr3_line_streamer.vhd tb_line_streamer.vhd"

echo "== analyze =="
"$GHDL" -a --std=08 $SRCS
echo "== elaborate + run =="
"$GHDL" --elab-run --std=08 tb_line_streamer --stop-time=10ms
echo "== done (expect 'ALL TESTS PASSED' above) =="
