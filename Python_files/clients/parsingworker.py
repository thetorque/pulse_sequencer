from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot, QMutex, QMutexLocker
from twisted.internet.defer import inlineCallbacks, returnValue  

import re
import numpy as np
import time

class ParsingWorker(QObject):
    parsing_done_trigger = pyqtSignal(list,int)
    finished = pyqtSignal(int)
    busy_trigger = pyqtSignal(bool)
    start = pyqtSignal()
    trackingparameterserver = pyqtSignal(bool)
    parsermessages = pyqtSignal(str)
    binary_trigger = pyqtSignal(list,int,tuple)

    def __init__(self,text,reactor,connection,cntx):
        super(ParsingWorker,self).__init__()
        self.text = text
        self.reactor = reactor
        self.connection = connection
        self.sequence = []
        self.defineRegexPatterns()
        self.start.connect(self.run)
        self.connectedsignal =False
        self.tracking = False
        self.trackingparameterserver.emit(self.tracking)
        self.ParameterID = 0
        self.Busy = False
        self.sequencestorage = []
        self.mutex = QMutex()
        


    def set_parameters(self,paramdict):
        self.parameters = paramdict

    def update_parameters(self,collection,name,value):
        if collection == "Raman" and name=="Parameters":
            time,shotID,mode,timetaken,boolean,A,B,C = value
            self.parameters['Raman']['A'] = A
            self.parameters['Raman']['B'] = B
            self.parameters['Raman']['C'] = C
            self.ParameterID = shotID
        else:
            self.parameters[collection][name] = value

        if self.tracking:
            self.run()

    def add_text(self,text):
        self.text = text
        
    def parse_text(self):
        self.sequence =  []
        defs,reducedtext =  self.findAndReplace(self.defpattern,self.text,re.DOTALL)
        if any(["ParameterVault" in d for d in defs]):
            self.tracking = True
            self.trackingparameterserver.emit(self.tracking)
        elif self.tracking == True:
            self.tracking = False
            self.trackingparameterserver.emit(self.tracking) 
        loops,reducedtext = self.findAndReplace(self.looppattern,reducedtext,re.DOTALL)
        self.parseDefine(defs,loops)
        self.parseLoop(loops)
        self.parsePulses(reducedtext)
        self.parsing_done_trigger.emit(self.sequence,self.ParameterID)
        self.get_binary_repres()


    def findAndReplace(self,pattern,string,flags=0):
        listofmatches = re.findall(pattern,string,flags)
        newstring = re.sub(pattern,'',string,re.DOTALL)
        return listofmatches,newstring

    def defineRegexPatterns(self):
        self.channelpattern = r'Channel\s+([aA0-zZ9]+)\s'
        self.pulsepattern   = r'([a-z]*)\s+([+-]?[0-9]+|[+-]?[0-9]+\.[0-9]+|var\s+[aA0-zZ9]+)\s+([aA-zZ]+)'
        self.looppattern    = r'#repeat\s+(.+?)\s+(.+?)\s*#endrepeat'
        self.defpattern     = r'#def\s+(.+?)\s*#enddef'
        self.modepattern    = r'in\s+mode\s+([aA-zZ]+)'

    def parseDefine(self,listofstrings,loops):
        for defblock in listofstrings:
            for line in defblock.strip().split('\n'):
                if '=' in line:
                    if "ParameterVault" in line.split():
                        line = re.sub(r'from|ParameterVault','',line)
                        param = line.split()[2]
                        line =re.sub(param,str(self.parameters['Raman'][param]),line)
                    exec('self.' + line.strip())
                else:
                    words = line.strip().split()
                    exec('self.'+words[1]+' = 0.0')


    def parseLoop(self,listofstrings):
        for loopparams, lines in listofstrings:
            begin,end,it = loopparams.split(',')
            lines = lines.strip()
            itervar = begin.split('=')[0]
            begin=int(begin.split('=')[1])
            it = int(it.split('+')[1])
            end = int(end.split('<')[1])
            newlines = ''
            for i in np.arange(begin,end,it):
                for aline in lines.split('\n'):
                    for amatch in re.findall(r'(\(.+?\))',aline):
                        if 'var' in amatch:
                            newsubstr = str(eval(amatch.replace('var ','self.')))
                            aline.replace(amatch,newsubstr)
                        elif itervar in amatch:
                            newsubstr = str(eval(amatch.replace(itervar,str(i))))
                            aline = aline.replace(amatch,newsubstr)
                    newlines += aline + '\n'
            self.parsePulses(newlines)


    def parsePulses(self,blockoftext):
        if len(blockoftext.strip())==0:
            return
        for line in blockoftext.strip().split('\n'):
            name,line = self.findAndReplace(self.channelpattern,line)
            mode,line = self.findAndReplace(self.modepattern,line)
            pulseparameters,line = self.findAndReplace(self.pulsepattern,line.strip())
            if mode[0] == 'Normal':
                self.makeNormalPulse(name,0,pulseparameters)

    def makeNormalPulse(self,name,mode,parameters):
        from labrad.units import WithUnit
        __freq, __amp, __begin, __dur = [0]*4
        __phase = WithUnit(0,"deg")
        __ramprate = WithUnit(0,'MHz')
        __ampramp = WithUnit(0,'dBm')

        for desig,value,unit in parameters:
            if   desig == 'do':
                try:
                    __freq = WithUnit(float(value),unit)
                except ValueError:
                    __freq = WithUnit(eval('self.'+value.split()[1].strip()),unit) 
            elif desig == 'at':
                try:
                    __begin = WithUnit(float(value),unit)
                except ValueError:
                    __begin = WithUnit(eval('self.'+value.split()[1].strip()),unit)
            elif desig == 'for':
                try:
                    __dur = WithUnit(float(value),unit)
                except ValueError:
                    __dur = WithUnit(eval('self.'+value.split()[1].strip()),unit)
            elif desig == 'with':
                try:
                    __amp = WithUnit(float(value),unit)
                except ValueError:
                    __amp = WithUnit(eval('self.'+value.split()[1].strip()),unit)
        self.sequence.append((name[0],__begin,__dur,__freq,__amp,__phase,__ramprate,__ampramp,mode))
    
    
    def get_binary_repres(self):
        import labrad
        try:
            p = labrad.connect().pulser
        except Exeption, e:
            parsermessages.emit('Parser \nDEBUG:\n'+repr(e))
        else:
            cont = p.context()
            p.new_sequence(context = cont)
            p.add_dds_standard_pulses(self.sequence,context = cont)
            binary = p.get_dds_program_representation(context = cont)
        self.mutex.tryLock()
        self.sequencestorage.append((binary,self.ParameterID,cont))
        print self.sequencestorage
        self.mutex.unlock()
        
    def get_sequence(self):
        locker = QMutexLocker(self.mutex)
        if len(self.sequencestorage)<2:
            currentsequence, currentID, currentcntx = self.sequencestorage[0]
        else:
            currentsequence, currentID, currentcntx = self.sequencestorage.pop(0)
        return currentsequence, currentID, currentcntx
        self.mutex.unlock()
        
        
    @pyqtSlot()
    def run(self):
        self.Busy = True
        self.busy_trigger.emit(self.Busy)
        self.parse_text()
        self.parsermessages.emit('Parser: Parsing done')
        self.Busy = False
        self.busy_trigger.emit(self.Busy)            