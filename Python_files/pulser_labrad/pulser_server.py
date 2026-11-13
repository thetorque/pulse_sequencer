"""
### BEGIN NODE INFO
[info]
name = Pulser
version = 2.0
description = XEM7305 pulse sequencer (py3, thin LabRAD re-expose of pulser3)
instancename = Pulser

[startup]
cmdline = %PYTHON% %FILE%
timeout = 20

[shutdown]
message = 987654321
timeout = 20
### END NODE INFO
"""
# pulser_server.py -- py3 LabRAD 'Pulser' server.
#
# A THIN re-expose of the headless pulser3 driver over LabRAD, for the modern
# scalabrad manager. Where the legacy servers/pulser/pulser_ok.py had the
# api/sequence/dds logic tangled inside the server, this keeps the same LabRAD
# setting IDs/names (so existing clients + the rest of the lab's LabRAD
# ecosystem work unchanged) and delegates every hardware action to pulser3.
#
# Settings: sequence build/program/run/stop, PMT counting + timetags, manual
# TTL switching, and DDS (legacy dds.py IDs 41-49 + 11 + 90-92; the DDS
# backplane bus of DDS_BUS_CONTRACT.md v0.3 through pulser3.dds_sequence).
#
# Blocking FPGA calls (USB) run in a thread via deferToThread, so they don't
# stall the Twisted reactor -- same pattern as the legacy server.
#
# Config: set PULSER_BIT_PATH to the photon .bit before starting the server.
import copy
import os
import sys
import time

# make the sibling pulser3 package importable when run as a standalone script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from labrad.server import LabradServer, setting, Signal   # noqa: E402
from labrad.units import WithUnit                          # noqa: E402
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredLock  # noqa: E402
from twisted.internet.threads import deferToThread        # noqa: E402

from pulser3 import Driver                                 # noqa: E402
from pulser3 import hwconfig                               # noqa: E402
from pulser3 import dds as D                               # noqa: E402
from pulser3 import dds_sequence as DS                     # noqa: E402

# PMT collection-mode state (LabRAD/server-layer, not hwconfig -- see hwconfig.py
# header). Collection time is the counting-gate length in seconds; the range is
# a sane bring-up window (the synthetic source and real detector both work here).
PMT_COLLECTION_TIME_RANGE_S = (0.001, 5.0)
PMT_DEFAULT_COLLECTION_S = 0.100
PMT_MODES = ('Normal', 'Differential')


class Pulser(LabradServer):
    """LabRAD front end for the XEM7305 pulse sequencer (delegates to pulser3)."""

    name = 'Pulser'

    # Fired when any switch is toggled, so other clients (GUIs) stay in sync.
    # Same ID/name/signature as the legacy server -> existing listeners work.
    onSwitch = Signal(611051, 'signal: switch toggled', '(ss)')
    # Fired when a DDS channel's frequency/amplitude/state changes (legacy dds.py).
    # (name, 'frequency'|'amplitude'|'state', value); state is sent as 1.0/0.0.
    on_dds_param = Signal(142006, 'signal: new dds parameter', '(ssv)')

    @inlineCallbacks
    def initServer(self):
        bit_path = os.environ.get('PULSER_BIT_PATH')
        if not bit_path:
            raise Exception("set PULSER_BIT_PATH to the photon .bit before starting")
        self.driver = Driver()
        self.inCommunication = DeferredLock()
        self.channels = hwconfig.CHANNELS
        self.sequence_range = hwconfig.SEQUENCE_TIME_RANGE_S
        # PMT counting state (mirrors legacy pulser_ok.py). collectionTime is the
        # gate length per mode; collectionMode selects which counter feeds the
        # FIFO; clear_next_pmt_counts drops the first N windows after a config
        # change (the startup transient -- e.g. differential window 0 = host-gap
        # photons before the first ch16 edge). synthetic/sim_rate drive the
        # on-FPGA bring-up source until the real detector is wired in.
        self.collectionMode = 'Normal'
        self.collectionTime = {'Normal': PMT_DEFAULT_COLLECTION_S,
                               'Differential': PMT_DEFAULT_COLLECTION_S}
        self.collectionTimeRange = PMT_COLLECTION_TIME_RANGE_S
        self.clear_next_pmt_counts = 0
        self.pmt_synthetic = True
        self.pmt_sim_rate = 1.0e5          # Hz, synthetic-source photon rate
        # per-channel manual-switch state (mirrors legacy channel objects):
        # ismanual, the remembered manual level, and the manual/auto invert
        # flags. Only channels wired for override (number < 12) are switchable.
        self.switchState = {
            name: {'ismanual': False, 'manualstate': False,
                   'manualinv': False, 'autoinv': False}
            for name in self.channels}
        self.listeners = set()             # client contexts, for signal fan-out
        # DDS: private copies of the configured channels (the server mutates the
        # manual state). ddsLock: set by programming a DDS sequence, cleared by
        # Stop Sequence / Clear DDS Lock -- manual changes are refused meanwhile,
        # since they rewrite row 0 of the loaded tables (legacy behaviour).
        self.ddsDict = copy.deepcopy(hwconfig.DDS_CHANNELS)
        DS.check_channels(self.ddsDict)
        self.ddsLock = False
        self.dds_programmed = False        # the loaded program has DDS tables
        print("Pulser: connecting to XEM7305 and configuring %s ..." % bit_path)
        yield deferToThread(self.driver.connect, bit_path)   # ConfigureFPGA + MIG calib
        print("Pulser: FPGA ready.")
        yield self.initializeDDS()

    # ---- sequence building (server-side Sequence per context) --------------
    @setting(0, "New Sequence", returns='')
    def newSequence(self, c):
        """Create a new (empty) pulse sequence in this context."""
        c['sequence'] = hwconfig.new_sequence()

    @setting(5, 'Add TTL Pulse', channel='s', start='v[s]', duration='v[s]')
    def addTTLPulse(self, c, channel, start, duration):
        """Add a TTL pulse on a named channel; times in seconds."""
        seq = c.get('sequence')
        if seq is None:
            raise Exception("Please create a new sequence first")
        if channel not in self.channels:
            raise Exception("Unknown channel %s" % channel)
        lo, hi = self.sequence_range
        s, d = start['s'], duration['s']
        if not (lo <= s <= hi and lo <= s + d <= hi):
            raise Exception("Time out of range")
        seq.add_pulse(channel, s, d)

    @setting(6, 'Add TTL Pulses', pulses='*(sv[s]v[s])')
    def addTTLPulses(self, c, pulses):
        """Add several TTL pulses at once (channel, start, duration)."""
        for channel, start, duration in pulses:
            yield self.addTTLPulse(c, channel, start, duration)

    @setting(7, "Extend Sequence Length", timeLength='v[s]')
    def extendSequenceLength(self, c, timeLength):
        """Extend the total sequence length (a no-op switch at timeLength)."""
        seq = c.get('sequence')
        if seq is None:
            raise Exception("Please create a new sequence first")
        seq.extend_length(timeLength['s'])

    # ---- program + run -----------------------------------------------------
    @setting(1, "Program Sequence", returns='')
    def programSequence(self, c):
        """Compile the current sequence and load it into DDR3."""
        seq = c.get('sequence')
        if seq is None:
            raise Exception("Please create a new sequence first")
        # TTL lines + (if the sequence has DDS pulses) the per-board DDS tables,
        # with AdvanceDDS/ResetDDS added. Compiled up front so a DDS error (e.g.
        # steps closer than 5 us) is reported before the hardware is touched.
        lines, dds_prog = DS.compile_sequence(seq, self.ddsDict)
        yield self.inCommunication.acquire()
        try:
            # Persistent-session cleanup: a prior start_single leaves the
            # streamer holding the shared MIG command channel (SEQMODE/START
            # still set), so a re-program must first clear ep00 + reset,
            # returning the channel to the write path. Without this the write
            # path never reaches idle (or the verify read mis-addresses) after
            # a few runs. Standalone scripts avoid it by reconfiguring per run.
            yield deferToThread(self.driver.stop)
            # verify=False: the readback is the roundtrip read path, which hits
            # the Phase-6b cold-start mis-address once the MIG has idled; the
            # WRITE is fine and the running sequence validates itself via
            # line_count / drop flags, so the verify is redundant in the server.
            yield deferToThread(self.driver.load_program, lines, verify=False)
            if dds_prog is not None:
                yield deferToThread(self._send_dds, dds_prog.frames())
        finally:
            self.inCommunication.release()
        self.isProgrammed = True
        self.dds_programmed = dds_prog is not None
        if self.dds_programmed:
            self.ddsLock = True

    @setting(4, "Start Single", returns='')
    def startSingle(self, c):
        """Run the programmed sequence once (DDR3 sequencer mode)."""
        yield self.inCommunication.acquire()
        try:
            yield self._rewind_dds()
            yield deferToThread(self.driver.start_single)
        finally:
            self.inCommunication.release()

    @setting(2, "Start Infinite", returns='')
    def startInfinite(self, c):
        """Run the programmed sequence, looping until stopped."""
        yield self.inCommunication.acquire()
        try:
            yield self._rewind_dds()
            yield deferToThread(self.driver.start_infinite)
        finally:
            self.inCommunication.release()

    @setting(9, "Start Number", repetition='w')
    def startNumber(self, c, repetition):
        """Run the programmed sequence a finite number of times."""
        yield self.inCommunication.acquire()
        try:
            yield self._rewind_dds()
            yield deferToThread(self.driver.start_number, int(repetition))
        finally:
            self.inCommunication.release()

    @setting(8, "Stop Sequence")
    def stopSequence(self, c):
        """Stop any running sequence."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.stop)
        finally:
            self.inCommunication.release()
        self.ddsLock = False

    @setting(16, 'Wait Sequence Done', timeout='v', returns='b')
    def waitSequenceDone(self, c, timeout=None):
        """Return True if the sequence finished within timeout seconds."""
        if timeout is None:
            timeout = self.sequence_range[1]
        done = yield deferToThread(self.driver.wait_done, float(timeout))
        returnValue(bool(done))

    @setting(17, 'Repeatitions Completed', returns='w')  # legacy spelling kept for API compat
    def repetitionsCompleted(self, c):
        """Completed iterations in infinite/number mode."""
        n = yield deferToThread(self.driver.seq_count)
        returnValue(int(n))

    @setting(3, 'Is Sequence Done', returns='b')
    def isSequenceDone(self, c):
        """Non-blocking: True if the sequence has finished (for progress polls;
        unlike Wait Sequence Done this returns immediately)."""
        done = yield deferToThread(self.driver.is_done)
        returnValue(bool(done))

    # ---- PMT photon counting (delegates to pulser3 PMT datapath) -----------
    # Same legacy setting IDs/names as servers/pulser/pulser_ok.py so existing
    # PMT clients work unchanged. Normal mode: the counter windows the input
    # over a fixed gate and pushes one count per window. Differential mode: the
    # running pulse sequence gates the windows (channel 16) and each count word
    # carries the 866 state (channel 0). Bring-up uses the on-FPGA synthetic
    # source; "Set PMT Synthetic" False selects the real detector pin.

    def _apply_pmt_mode(self):
        """Drive ep08 to the current mode + gate + synthetic state (blocking)."""
        gate = self.driver.seconds_to_cycles(self.collectionTime[self.collectionMode])
        period = self.driver.rate_to_period(self.pmt_sim_rate)
        if self.collectionMode == 'Differential':
            # windows come from the running sequence's ch16; count_en not used
            self.driver.pmt_diff_start(synthetic=self.pmt_synthetic,
                                       period_cycles=period)
        else:
            self.driver.pmt_set_mode(False)
            self.driver.pmt_configure(gate_cycles=gate, period_cycles=period)
            self.driver.pmt_start(synthetic=self.pmt_synthetic)

    @setting(21, 'Set Mode', mode='s', returns='')
    def setMode(self, c, mode):
        """Set the counting mode, 'Normal' or 'Differential'.

        Normal: the FPGA windows counts at the collection-time rate. Differential:
        the running pulse sequence gates the windows and reports the 866 state.
        """
        if mode not in PMT_MODES:
            raise Exception("Incorrect mode (use 'Normal' or 'Differential')")
        self.collectionMode = mode
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self._apply_pmt_mode)
            self.clear_next_pmt_counts = 3   # drop the config-change transient
        finally:
            self.inCommunication.release()

    @setting(22, 'Set Collection Time', new_time='v', mode='s', returns='')
    def setCollectTime(self, c, new_time, mode):
        """Set the photon collection (gate) time in seconds for the given mode."""
        new_time = float(new_time)
        lo, hi = self.collectionTimeRange
        if not lo <= new_time <= hi:
            raise Exception("collection time out of range")
        if mode not in PMT_MODES:
            raise Exception("Incorrect mode")
        self.collectionTime[mode] = new_time
        yield self.inCommunication.acquire()
        try:
            # Only Normal's gate is a device setting; Differential is gated by
            # the sequence, so its collection time is only used for the KC/sec
            # conversion below. Re-apply if we changed the active Normal gate.
            if mode == 'Normal' and self.collectionMode == 'Normal':
                yield deferToThread(self._apply_pmt_mode)
            self.clear_next_pmt_counts = 3
        finally:
            self.inCommunication.release()

    @setting(23, 'Get Collection Time', returns='(vv)')
    def getCollectTime(self, c):
        """The allowed (min, max) collection time in seconds."""
        return self.collectionTimeRange

    @setting(24, 'Reset FIFO Normal', returns='')
    def resetFIFONormal(self, c):
        """Clear the on-board normal/differential count FIFO."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.pmt_reset_fifo)
        finally:
            self.inCommunication.release()

    @setting(25, 'Get PMT Counts', returns='*(vsv)')
    def getALLCounts(self, c):
        """Queued counts as (rate_kc_per_s, status, time) tuples.

        status is 'ON' in Normal mode; in Differential mode it is 'ON'/'OFF' for
        the 866 state of that window. time is the approximate acquisition time.
        """
        yield self.inCommunication.acquire()
        try:
            countlist = yield deferToThread(self._do_get_all_counts)
        finally:
            self.inCommunication.release()
        returnValue(countlist)

    def _do_get_all_counts(self):
        """Blocking: read the FIFO, decode, convert to KC/sec, timestamp."""
        collect = self.collectionTime[self.collectionMode]
        now = time.time()
        rows = []
        if self.collectionMode == 'Differential':
            for count, is_866_on in self.driver.pmt_read_diff_counts():
                rows.append([count, 'ON' if is_866_on else 'OFF'])
        else:
            for count in self.driver.pmt_read_counts():
                rows.append([count, 'ON'])
        # drop the first few windows after a config change (startup transient)
        while self.clear_next_pmt_counts and rows:
            rows.pop(0)
            self.clear_next_pmt_counts -= 1
        out = []
        n = len(rows)
        for i, (count, status) in enumerate(rows):
            kc = float(count) / collect / 1000.0
            # guess arrival times: the last row is "now", earlier ones back off
            t = now - (n - 1 - i) * collect
            out.append((kc, status, t))
        return out

    @setting(28, 'Get Collection Mode', returns='s')
    def getMode(self, c):
        """The active counting mode ('Normal' or 'Differential')."""
        return self.collectionMode

    @setting(19, 'Set PMT Synthetic', synthetic='b', returns='')
    def setPMTSynthetic(self, c, synthetic):
        """Select the on-FPGA synthetic photon source (True, bring-up) vs the
        real detector input (False). Re-applies the active mode."""
        self.pmt_synthetic = bool(synthetic)
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self._apply_pmt_mode)
            self.clear_next_pmt_counts = 3
        finally:
            self.inCommunication.release()

    @setting(20, 'Set PMT Sim Rate', rate='v', returns='')
    def setPMTSimRate(self, c, rate):
        """Set the synthetic source photon rate in Hz (bring-up only)."""
        rate = float(rate)
        if rate <= 0:
            raise Exception("sim rate must be positive")
        self.pmt_sim_rate = rate
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self._apply_pmt_mode)
            self.clear_next_pmt_counts = 3
        finally:
            self.inCommunication.release()

    # ---- PMT time-resolved timetagging -------------------------------------
    @setting(31, 'Reset Timetags', returns='')
    def resetTimetags(self, c):
        """Clear the time-resolved (photon-timestamp) FIFO."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.pmt_timetag_reset)
        finally:
            self.inCommunication.release()

    @setting(30, 'Record Timetags', record='b', returns='')
    def recordTimetags(self, c, record):
        """Open (True) or close (False) the photon-timestamp detection window."""
        yield self.inCommunication.acquire()
        try:
            if record:
                period = self.driver.rate_to_period(self.pmt_sim_rate)
                yield deferToThread(self.driver.pmt_record_start,
                                    self.pmt_synthetic, period)
            else:
                yield deferToThread(self.driver.pmt_record_stop)
        finally:
            self.inCommunication.release()

    @setting(32, 'Get Timetags', returns='*v')
    def getTimetags(self, c):
        """Recorded photon arrival times, in seconds (5 ns resolution)."""
        yield self.inCommunication.acquire()
        try:
            ticks = yield deferToThread(self.driver.pmt_read_timetags)
        finally:
            self.inCommunication.release()
        returnValue([self.driver.ticks_to_seconds(t) for t in ticks])

    @setting(33, 'Get TimeTag Resolution', returns='v')
    def getTimeTagResolution(self, c):
        """Timetag tick resolution in seconds."""
        from pulser3 import wiremap as W
        return W.TIMETAG_RESOLUTION_S

    # ---- manual TTL switching (per-channel override) -----------------------
    # Force a TTL output ON/OFF independently of the sequence, or return it to
    # sequence ('Auto') control. Same legacy setting IDs/names + switch-toggled
    # signal so the GUI clients work unchanged. Hardware override is wired for
    # channel numbers 0..11 only (pulser3 raises for higher ones).

    @staticmethod
    def _cnot(control, value):
        """Conditional NOT: flip value when control is set (legacy cnot)."""
        return (not value) if control else value

    def _notify_switch(self, c, channel_name, label):
        """Fire onSwitch to every listener except the caller's context."""
        others = self.listeners.copy()
        others.discard(c.ID)
        self.onSwitch((channel_name, label), others)

    @setting(13, 'Switch Manual', channelName='s', state='b', returns='')
    def switchManual(self, c, channelName, state=None):
        """Force a channel ON/OFF (manual override). With no state, reuse the
        last remembered manual level."""
        if channelName not in self.switchState:
            raise Exception("Incorrect Channel")
        st = self.switchState[channelName]
        st['ismanual'] = True
        if state is not None:
            st['manualstate'] = bool(state)
        level = st['manualstate']
        number = self.channels[channelName]
        yield self.inCommunication.acquire()
        try:
            # manual invert flag is folded into the forced level, as legacy did
            yield deferToThread(self.driver.set_manual, number,
                                self._cnot(st['manualinv'], level))
        finally:
            self.inCommunication.release()
        self._notify_switch(c, channelName, 'ManualOn' if level else 'ManualOff')

    @setting(14, 'Switch Auto', channelName='s', invert='b', returns='')
    def switchAuto(self, c, channelName, invert=None):
        """Return a channel to sequence ('Auto') control, optionally inverted."""
        if channelName not in self.switchState:
            raise Exception("Incorrect Channel")
        st = self.switchState[channelName]
        st['ismanual'] = False
        if invert is not None:
            st['autoinv'] = bool(invert)
        number = self.channels[channelName]
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.set_auto, number, st['autoinv'])
        finally:
            self.inCommunication.release()
        self._notify_switch(c, channelName, 'Auto')

    @setting(15, 'Get State', channelName='s', returns='(bbbb)')
    def getState(self, c, channelName):
        """(ismanual, manualstate, manualinv, autoinv) for a channel."""
        if channelName not in self.switchState:
            raise Exception("Incorrect Channel")
        st = self.switchState[channelName]
        return (st['ismanual'], st['manualstate'], st['manualinv'], st['autoinv'])

    # ---- DDS (backplane bus, pulser3.dds_sequence) --------------------------
    # Same setting IDs/names/signatures as the legacy servers/pulser/dds.py so
    # experiment code (Add DDS Pulses) and DDS GUI clients work unchanged.
    # Differences on the 2026 hardware: "off" opens the RF switch (contract
    # decision 2), there are no ramps (the Movinglattice setting 50 is gone and
    # non-zero ramp rates are refused), and DDS changes in a sequence must be
    # >= 5 us apart. Manual settings rewrite the channel's row 0 and RESET its
    # board, so the new value appears at once.

    def _send_dds(self, frames):
        """Blocking: queue frames on pipe 0x81 and wait until they are on the bus."""
        self.driver.dds_send(frames)
        time.sleep(DS.bus_seconds(frames))

    def _rewind_dds(self):
        """Before a run: put every board on row 0 with a RESET frame. The
        sequence's own ResetDDS pulse does this at the end of each run, but only
        where the RAMRESET line is wired; the frame always works. Deferred."""
        if not self.dds_programmed:
            return deferToThread(lambda: None)
        return deferToThread(self._send_dds, [D.reset()])

    def _dds_channel(self, name):
        if name is None:
            raise Exception("DDS channel name required (one of %s)" % sorted(self.ddsDict))
        try:
            return self.ddsDict[name]
        except KeyError:
            raise Exception("Channel {0} not found".format(name))

    def _check_dds_lock(self):
        if self.ddsLock:
            raise Exception("DDS access is locked: a DDS sequence is programmed. "
                            "Stop Sequence or Clear DDS Lock first.")

    def _apply_manual(self, ch):
        """Blocking: make the board output the channel's manual state now."""
        self._send_dds([D.write_rows(ch.addr, 0, [ch.manual_row()]), D.reset(ch.addr)])

    def _notify_dds(self, c, name, item, value):
        others = self.listeners.copy()
        others.discard(c.ID)
        self.on_dds_param((name, item, float(value)), others)

    @inlineCallbacks
    def initializeDDS(self):
        """Every configured channel to its manual state (legacy initializeDDS).
        Also the first pipe-0x81 traffic, so it flushes the frame FIFO first."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.dds_clear)
            for ch in self.ddsDict.values():
                yield deferToThread(self._apply_manual, ch)
        finally:
            self.inCommunication.release()

    @setting(41, "Get DDS Channels", returns='*s')
    def getDDSChannels(self, c):
        """Names of the DDS channels (hwconfig.DDS_CHANNELS)."""
        return list(self.ddsDict.keys())

    @setting(43, "Amplitude", name='s', amplitude='v[dBm]', returns='v[dBm]')
    def amplitude(self, c, name=None, amplitude=None):
        """Get or set the manual amplitude (dBm) of a DDS channel. If the channel
        is on, the output changes immediately."""
        ch = self._dds_channel(name)
        if amplitude is not None:
            self._check_dds_lock()
            amplitude = amplitude['dBm']
            ch.check(amplitude_dbm=amplitude)
            ch.amplitude_dbm = amplitude
            if ch.on:
                yield self.inCommunication.acquire()
                try:
                    yield deferToThread(self._apply_manual, ch)
                finally:
                    self.inCommunication.release()
            self._notify_dds(c, name, 'amplitude', amplitude)
        returnValue(WithUnit(ch.amplitude_dbm, 'dBm'))

    @setting(44, "Frequency", name='s', frequency='v[MHz]', returns='v[MHz]')
    def frequency(self, c, name=None, frequency=None):
        """Get or set the manual frequency (MHz) of a DDS channel. The frequency
        is always loaded (the RF switch decides on/off), keeping phase continuity."""
        ch = self._dds_channel(name)
        if frequency is not None:
            self._check_dds_lock()
            frequency = frequency['MHz']
            ch.check(frequency_mhz=frequency)
            ch.frequency_mhz = frequency
            yield self.inCommunication.acquire()
            try:
                yield deferToThread(self._apply_manual, ch)
            finally:
                self.inCommunication.release()
            self._notify_dds(c, name, 'frequency', frequency)
        returnValue(WithUnit(ch.frequency_mhz, 'MHz'))

    @setting(48, 'Output', name='s', state='b', returns='b')
    def output(self, c, name=None, state=None):
        """Get or set a DDS channel's manual on/off (off = RF switch open)."""
        ch = self._dds_channel(name)
        if state is not None:
            self._check_dds_lock()
            ch.on = bool(state)
            yield self.inCommunication.acquire()
            try:
                yield deferToThread(self._apply_manual, ch)
            finally:
                self.inCommunication.release()
            self._notify_dds(c, name, 'state', ch.on)
        returnValue(ch.on)

    @setting(45, 'Add DDS Pulses',
             values=['*(sv[s]v[s]v[MHz]v[dBm])',
                     '*(sv[s]v[s]v[MHz]v[dBm]v[deg]v[MHz]v[dB])'])
    def addDDSPulses(self, c, values):
        """Add DDS pulses to this context's sequence:
        [(name, start, duration, frequency, amplitude[, phase, ramp_rate, amp_ramp_rate])].
        Frequency 0 = off; 0-length pulses are ignored; ramp rates must be 0."""
        seq = c.get('sequence')
        if seq is None:
            raise Exception("Please create a new sequence first")
        lo, hi = self.sequence_range
        for value in values:
            if len(value) == 5:
                name, start, dur, freq, ampl = value
                phase, ramp, amp_ramp = 0.0, 0.0, 0.0
            else:
                name, start, dur, freq, ampl, phase, ramp, amp_ramp = value
                phase, ramp, amp_ramp = phase['deg'], ramp['MHz'], amp_ramp['dB']
            ch = self._dds_channel(name)
            start, dur = start['s'], dur['s']
            if not (lo < start <= hi and lo < start + dur <= hi):
                raise Exception("DDS start time out of acceptable input range for "
                                "channel {0} at time {1}".format(name, start))
            DS.add_dds_pulse(seq, ch, start, dur, freq['MHz'], ampl['dBm'],
                             phase, ramp, amp_ramp)

    @setting(46, 'Get DDS Amplitude Range', name='s', returns='(vv)')
    def getDDSAmplRange(self, c, name=None):
        """Allowed (min, max) amplitude in dBm (the channel's calibration range)."""
        return self._dds_channel(name).amp_range_dbm

    @setting(47, 'Get DDS Frequency Range', name='s', returns='(vv)')
    def getDDSFreqRange(self, c, name=None):
        """Allowed (min, max) frequency in MHz."""
        return self._dds_channel(name).freq_range_mhz

    @setting(49, 'Clear DDS Lock')
    def clear_dds_lock(self, c):
        """Allow manual DDS changes again while a DDS sequence is loaded."""
        self.ddsLock = False

    @setting(11, "Human Readable DDS", returns='*(svv)')
    def humanReadableDDS(self, c):
        """The DDS tables this context's sequence compiles to, one
        (name, frequency MHz, amplitude dBm) per channel per row, row 0 first.
        A row with the RF switch open reports amplitude -inf."""
        seq = c.get('sequence')
        if seq is None:
            raise Exception("Please create a new sequence first")
        _, prog = DS.compile_sequence(seq, self.ddsDict)
        if prog is None:
            return []
        out = []
        for _, rows in prog.describe():
            for name, r in rows.items():
                cal = self.ddsDict[name].cal
                dbm = (r.vga - cal.code_at_0dbm) / cal.codes_per_db if r.rf_on else float('-inf')
                out.append((name, r.freq_hz / 1e6, dbm))
        return out

    @setting(90, 'Internal Reset DDS', returns='')
    def internal_reset_dds(self, c):
        """Debug: all DDS boards back to row 0 (RESET frame)."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self._send_dds, [D.reset()])
        finally:
            self.inCommunication.release()

    @setting(91, 'Internal Advance DDS', returns='')
    def internal_advance_dds(self, c):
        """Debug: one STEPNEXT pulse to all DDS boards."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.dds_step)
        finally:
            self.inCommunication.release()

    @setting(92, "Reinitialize DDS", returns='')
    def reinitializeDDS(self, c):
        """Every DDS channel back to its manual state (row 0 rewritten + RESET).
        The AD9912 itself is initialised by its board at power-up."""
        self.dds_programmed = False
        self.ddsLock = False
        yield self.initializeDDS()

    # ---- listener bookkeeping (for the switch-toggled signal) --------------
    def initContext(self, c):
        self.listeners.add(c.ID)

    def expireContext(self, c):
        self.listeners.discard(c.ID)

    # ---- introspection -----------------------------------------------------
    @setting(12, 'Get Channels', returns='*(sw)')
    def getChannels(self, c):
        """All channel names and their hardware numbers."""
        return [(name, num) for name, num in sorted(self.channels.items(),
                                                     key=lambda kv: (kv[1], kv[0]))]


if __name__ == "__main__":
    from labrad import util
    util.runServer(Pulser())
