from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot, QTimer
from twisted.internet.defer import inlineCallbacks

import time


class PulserWorker(QObject):

    startsignal = pyqtSignal()
    stopsignal = pyqtSignal()
    loopsignal = pyqtSignal()
    pulsermessages = pyqtSignal(str)
    sequence_done_trigger = pyqtSignal(int,bool)

    def __init__(self,reactor,connection,parsingworker):
        
        super(PulserWorker,self).__init__()
        self.reactor = reactor
        self.parsingworker = parsingworker
        self.parsingworker.new_sequence_trigger.connect(self.run)
        self.connection = connection
        self.sequencestorage = []
        self.startsignal.connect(self.run)
        self.stopsignal.connect(self.stop)
        self.loopsignal.connect(self.loop)
        self.running = False
        self.stopping=False

    def set_shottime(self,time):
        self.shottime = time

    def stop(self):
        self.stopping = True
        self.pulsermessages.emit('Pulser: Stopped')

    def timed_out(self):
        print 'timed out'
        self.pulsermessages.emit('Pulser: Pulser timed out')

        
    def do_sequence(self,currentsequence,currentttl,currentID):
        import labrad
        cnx = labrad.connect()
        p = cnx.pulser
        self.pulsermessages.emit('Pulser: Programming:' + str(currentID))
        p.new_sequence()
        #tic = time.clock()
        #p.stop_sequence()
        p.program_dds_and_ttl(currentsequence,currentttl)
        #toc = time.clock()
        #print "programmed ", toc-tic
        self.pulsermessages.emit('Pulser: Running:' + str(currentID))
        p.start_number(1)
        #toc = time.clock()
        #print 'Programming and starting time: ',toc-tic
        try:
            #tic = time.clock()
            p.wait_sequence_done(timeout=self.shottime)
            counts = p.get_metablock_counts()
            
            
            p.stop_sequence() #The stop signal stops the loop *if more than one repetition was set, and resets the OKfpga (the ttltimings)
            #toc = time.clock()
            #print 'Sequence done:                 ',toc-tic
        except labrad.errors.RequestTimeoutError, e:
            p.stop_sequence()
            print repr(e)
            self.pulsermessages.emit('Pulser: Timed out')
        else:
            #print 'time done:       ',time.time()
            self.sequence_done_trigger.emit(currentID,True)
            
            self.pulsermessages.emit('Metablock counts: '+ str(counts[0]))

        cnx.disconnect()
        
    
    @pyqtSlot()
    def run(self):
        while not self.stopping:
            currentsequence, currentttl, currentID = self.parsingworker.get_sequence()
            if None in (currentsequence, currentttl, currentID):
                #self.pulsermessages.emit('Pulser: Error in retrieveing sequence from parser')
                time.sleep(0.2)
            else:
                self.stopping = True
                self.do_sequence(currentsequence, currentttl, currentID)
            
        self.stopping = False
        
    @pyqtSlot()    
    def loop(self):
        import labrad
        cnx = labrad.connect()
        p = cnx.pulser
        self.pulsermessages.emit('Pulser: Looping beginning')
        while not self.stopping:
            p.start_number(1)
            p.wait_sequence_done(timeout=self.shottime)
            p.stop_sequence()
            time.sleep(0.1)
        cnx.disconnect()
        self.stopping = False
        