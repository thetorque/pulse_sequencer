from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot
from twisted.internet.defer import inlineCallbacks, returnValue
import re
import numpy as np
import time

class ParsingWorker(QObject):
    parsed_trigger = pyqtSignal(list)
    finished = pyqtSignal(int)
    busy = pyqtSignal()
    start = pyqtSignal()
    trackingparameterserver = pyqtSignal(bool)
    parsermessages = pyqtSignal(str)

    def __init__(self,reactor,connection,text):
        super(ParsingWorker,self).__init__()
        self.reactor = reactor
        self.connection = connection
        self.text = text
        self.sequence = []
        self.defineRegexPatterns()
        self.start.connect(self.run)
        self.connectedsignal =False
        self.tracking = False
        self.trackingparameterserver.emit(self.tracking)
        self.ParameterID = 0

    def set_parameters(self,paramdict):
        self.parameters = paramdict

    def update_parameters(self,collection,name,value):
        if collection == "Raman" and name=="Parameters":
            time,shotID,boolean,A,B,C = value
            self.parameters['Raman']['A'] = A
            self.parameters['Raman']['B'] = A
            self.parameters['Raman']['C'] = A
            self.ParameterID = shotID
        else:
            self.parameters[collection][name] = value

        if self.tracking:
            self.run()

    def add_text(self,text):
        self.text = text

    def parse_text(self):
        self.busy.emit()
        self.sequence = []
        defs,reducedtext = self.findAndReplace(self.defpattern,self.text,re.DOTALL)
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

    @inlineCallbacks
    def program_sequence(self):
        server = yield self.connection.get_server('Pulser')
        yield server.new_sequence()
        yield server.add_dds_standard_pulses(self.sequence)
        yield server.program_sequence()

    @pyqtSlot()
    def run(self):
        self.parse_text()
        self.parsermessages.emit('Parser: Parsing done')
        self.parsed_trigger.emit(self.sequence)
        #self.program_sequence()
        self.finished.emit(0)