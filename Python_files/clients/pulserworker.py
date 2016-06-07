from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot, QTimer
from twisted.internet.defer import inlineCallbacks
import time


class PulserWorker(QObject):

    startsignal = pyqtSignal()
    stopsignal = pyqtSignal()
    pulsermessages = pyqtSignal(str)
    sequence_done_trigger = pyqtSignal(int)

    def __init__(self,reactor,connection,parsingworker):
        
        super(PulserWorker,self).__init__()
        self.reactor = reactor
        self.parsingworker = parsingworker
        self.connection = connection
        self.sequencestorage = []
        self.startsignal.connect(self.run)
        self.stopsignal.connect(self.stop)
        self.running = False
        self.stopping=False

    def set_shottime(self,time):
        self.shottime = time


    @pyqtSlot(int,int)
    def new_binary_sequence(self,binary,ID,cntx):
        self.sequencestorage.append((binary,ID,cntx))
        print 'signal receiving'
        self.run()

    def stop(self):
        self.stopping = True

    def timed_out(self):
        print 'timed out'
        self.pulsermessages.emit('Pulser: Pulser timed out')

        
    def do_sequence(self,currentsequence,currentID,currentcntx):
        import labrad
        p = labrad.connect().pulser
        self.pulsermessages.emit('Pulser: Programming:' + str(currentID))
        p.program_dds(currentsequence,context = currentcntx)
        self.pulsermessages.emit('Pulser: Running:' + str(currentID))
        p.start_number(1)
        try:
            p.wait_sequence_done(timeout=self.shottime)
        except labrad.errors.RequestTimeoutError, e:
            p.stop_sequence()
            print repr(e)
            self.pulsermessages.emit('Pulser: Timed out')
        else:
            self.sequence_done_trigger.emit(currentID)
        
    
    @pyqtSlot()
    def run(self):
        while not self.stopping:
            try:
                print 'trying to get sequence'
                currentsequence, currentID, context = self.parsingworker.get_sequence()
            except IndexError, e:
                self.pulsermessages.emit('Pulser: Error in retrieveing sequence from parser')
                time.sleep(2)
                print 'done sleeping'
            else:
                print 'got sequence, doing something'
                self.do_sequence(currentsequence, currentID, context)
            
        self.stopping = False
        self.pulsermessages.emit('Pulser: Stopped')