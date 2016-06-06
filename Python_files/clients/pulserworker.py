from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot, QTimer
from twisted.internet.defer import inlineCallbacks

class PulserWorker(QObject):


    startsignal = pyqtSignal()
    stopsignal = pyqtSignal()
    pulsermessages = pyqtSignal(str)

    def __init__(self,reactor,connection):
        super(PulserWorker,self).__init__()
        self.reactor = reactor
        self.connection = connection
        self.sequencestorage = []
        self.startsignal.connect(self.run)
        self.stopsignal.connect(self.stop)
        self.timer = QTimer()
        self.timer.timeout.connect(self.run)
        self.running = False

    def set_shottime(self,time):
        self.shottime = time

    @pyqtSlot()
    def new_binary_sequence(self,binary,ID):
        print binary,ID
        self.sequencestorage.append((binary,ID))
        self.run()

    def stop(self):
        self.stopping = True

    def timed_out(self):
        self.pulsermessages.emit('Pulser: Pulser timed out')

    @inlineCallbacks
    @pyqtSlot()
    def run(self):
        if not self.stopping:
            self.timer(self.shottime+100) #Shottime + 100 ms just to be sure ??
            p = yield self.connection.get_server('Pulser')
            if self.running == True:
                p.stop_sequence()

            if len(self.sequencestorage)>2:
                currentsequence, currentID = self.sequencestorage[0]
            else:
                currentsequence, currentID = self.sequencestorage.pop(0)
            self.pulsermessages.emit('Pulser: Programming:' + str(currentID))
            p.program_dds(currentsequence)
            self.running = True
            self.pulsermessages.emit('Pulser: Running:' + str(currentID))
            p.start()
        else:
            self.stopping = False