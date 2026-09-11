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
# This is the MINIMAL proof-of-stack server (sequence build/program/run/stop);
# the full setting set (PMT counting, DDS, switch manual/auto) is added next.
#
# Blocking FPGA calls (USB) run in a thread via deferToThread, so they don't
# stall the Twisted reactor -- same pattern as the legacy server.
#
# Config: set PULSER_BIT_PATH to the photon .bit before starting the server.
import os
import sys

# make the sibling pulser3 package importable when run as a standalone script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from labrad.server import LabradServer, setting          # noqa: E402
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredLock  # noqa: E402
from twisted.internet.threads import deferToThread        # noqa: E402

from pulser3 import Driver                                 # noqa: E402
from pulser3 import hwconfig                               # noqa: E402


class Pulser(LabradServer):
    """LabRAD front end for the XEM7305 pulse sequencer (delegates to pulser3)."""

    name = 'Pulser'

    @inlineCallbacks
    def initServer(self):
        bit_path = os.environ.get('PULSER_BIT_PATH')
        if not bit_path:
            raise Exception("set PULSER_BIT_PATH to the photon .bit before starting")
        self.driver = Driver()
        self.inCommunication = DeferredLock()
        self.channels = hwconfig.CHANNELS
        self.sequence_range = hwconfig.SEQUENCE_TIME_RANGE_S
        print("Pulser: connecting to XEM7305 and configuring %s ..." % bit_path)
        yield deferToThread(self.driver.connect, bit_path)   # ConfigureFPGA + MIG calib
        print("Pulser: FPGA ready.")

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
        lines = seq.to_lines()
        yield self.inCommunication.acquire()
        try:
            # verify=False: this server keeps ONE FPGA session across many runs,
            # so the MIG idles between them. The write-verify readback is the
            # roundtrip read path, which hits the Phase-6b cold-start
            # mis-address after an idle (the WRITE is fine; only that read
            # mis-addresses). The standalone scripts avoid it by reconfiguring
            # (fresh calibration) each run. The running sequence validates
            # itself via line_count / drop flags, so the verify is redundant here.
            yield deferToThread(self.driver.load_program, lines, verify=False)
        finally:
            self.inCommunication.release()
        self.isProgrammed = True

    @setting(4, "Start Single", returns='')
    def startSingle(self, c):
        """Run the programmed sequence once (DDR3 sequencer mode)."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.start_single)
        finally:
            self.inCommunication.release()

    @setting(2, "Start Infinite", returns='')
    def startInfinite(self, c):
        """Run the programmed sequence, looping until stopped."""
        yield self.inCommunication.acquire()
        try:
            yield deferToThread(self.driver.start_infinite)
        finally:
            self.inCommunication.release()

    @setting(9, "Start Number", repetition='w')
    def startNumber(self, c, repetition):
        """Run the programmed sequence a finite number of times."""
        yield self.inCommunication.acquire()
        try:
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

    # ---- introspection -----------------------------------------------------
    @setting(12, 'Get Channels', returns='*(sw)')
    def getChannels(self, c):
        """All channel names and their hardware numbers."""
        return [(name, num) for name, num in sorted(self.channels.items(),
                                                     key=lambda kv: (kv[1], kv[0]))]


if __name__ == "__main__":
    from labrad import util
    util.runServer(Pulser())
