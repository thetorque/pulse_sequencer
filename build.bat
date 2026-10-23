@echo off
REM ===========================================================================
REM build.bat -- portable remote-build wrapper for the XEM7305 pulser bitstream.
REM
REM Place/keep at the repo root. Run on the Windows bench (locally or over SSH):
REM
REM   build.bat            incremental build  (open project, rebuild changed)
REM   build.bat fresh      recreate the Vivado project from scratch (slow)
REM   build.bat clean      reset the runs, then rebuild
REM
REM Portable: it cd's to its own folder (= repo root) and auto-detects the
REM newest Vivado under the common AMD/Xilinx install roots, so there are no
REM machine-specific paths to edit. Override by setting VIVADO_SETTINGS before
REM calling, e.g.  set "VIVADO_SETTINGS=D:\tools\Vivado\2025.2\settings64.bat"
REM ===========================================================================
setlocal

REM --- locate Vivado's settings64.bat (newest version wins) ------------------
if not defined VIVADO_SETTINGS (
  for %%R in ("C:\AMDDesignTools" "C:\Xilinx" "C:\AMD") do (
    if exist "%%~R" for /f "delims=" %%V in ('dir /b /ad /o-n "%%~R" 2^>nul') do (
      if exist "%%~R\%%V\Vivado\settings64.bat" if not defined VIVADO_SETTINGS set "VIVADO_SETTINGS=%%~R\%%V\Vivado\settings64.bat"
    )
  )
)
if not defined VIVADO_SETTINGS (
  echo ERROR: could not find Vivado settings64.bat under C:\AMDDesignTools, C:\Xilinx or C:\AMD.
  echo        Set VIVADO_SETTINGS to the full path and re-run.
  exit /b 1
)
echo Using Vivado: %VIVADO_SETTINGS%
call "%VIVADO_SETTINGS%"

REM --- sync sources + build --------------------------------------------------
cd /d "%~dp0"
git pull
vivado -mode batch -source VHDL_files\XEM7305_Pulser_2026_09_07\build.tcl -tclargs %*
exit /b %ERRORLEVEL%
