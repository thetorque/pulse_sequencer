from twisted.internet.defer import inlineCallbacks
from PyQt4 import QtGui
from PyQt4.QtCore import pyqtSignal
import re

SIGNALID = 489136

class writingwidget(QtGui.QWidget):
    parsed_trigger = pyqtSignal(list)

    def __init__(self,reactor, connection =None, parent= None):
        super(writingwidget,self).__init__()
        self.reactor = reactor
        self.connection = connection
        self.defineRegexPatterns()
        self.setupLayout()

    def setupLayout(self):
        layout=QtGui.QVBoxLayout(self)
        self.textedit = QtGui.QTextEdit()
        string = "'Raman_rad', WithUnit(0.1, 'ms'), WithUnit(999.9, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0 \n"
        string +=  "'Raman_ax', WithUnit(1000, 'ms'), WithUnit(3000, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0 \n"
        string +=  "'Raman_rad', WithUnit(1002, 'ms'), WithUnit(3000, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0   \n"
        string = "#def\n"
        string +="var A0\n"
        string +="#enddef\n"
        string +="\n"
        string +="#def\n"
        string +="var T_start = 10\n"
        string +="#enddef\n"
        string +="\n"
        string +="#repeat 10\n"
        string +="\n"
        string +="Channel U_Fo12ria do 30  MHz with var A0 dBm for 300 ms at 20 ms in mode Normal\n"
        string +="\n"
        string +="#endrepeat\n\n\n"
        string +="#repeat 15\n"
        string +="\n"
        string +="Channel Raman_ax do 40  MHz with 20 dBm for var T_start ms at 20 ms in mode Normal\n"
        string +="\n"
        string +="#endrepeat\n"
        string +="Channel Raman_rad do 300  MHz with 10 dBm for var T_start ms at 40 ms in mode Normal\n"
        string +="Channel Raman_ax do 200  MHz with 2 dBm for var T_start ms at 40 ms in mode Normal\n"
        string +="Channel DDS_1 do 100  MHz with -20 dBm for var T_start ms at 60 ms in mode Normal\n"

        self.textedit.setPlainText(string)
       
        self.parse = QtGui.QPushButton('Parse')
        self.parse.pressed.connect(self.on_parse)


        layout.addWidget(self.parse)
        layout.addWidget(self.textedit)
        self.setLayout(layout)

    @inlineCallbacks
    def setupListeners(self):
        server = yield self.connection.get_server('ParameterVault')
        yield server.signal__paramter_change(SIGNALID)
        yield server.addListener(listener = self.on_parameterchange, source = None, ID = SignalID)

    def on_parse(self):
        
        self.sequence = []
        # read text from textbox
        text = str(self.textedit.toPlainText())
        defs,text = self.findAndReplace(self.defpattern,text,re.DOTALL)
        self.parseDefine(defs)
        loops,text = self.findAndReplace(self.looppattern,text,re.DOTALL)
        for line in text.strip().split('\n'):
            name,line = self.findAndReplace(self.channelpattern,line)
            mode,line = self.findAndReplace(self.modepattern,line)
            pulseparameters,line = self.findAndReplace(self.pulsepattern,line.strip())
            if mode[0] == 'Normal':
                self.makeNormalPulse(name,0,pulseparameters)
        self.parsed_trigger.emit(self.sequence)

    def findAndReplace(self,pattern,string,flags=0):
        listofmatches = re.findall(pattern,string,flags)
        newstring = re.sub(pattern,'',string,flags)
        return listofmatches,newstring

    @inlineCallbacks
    def on_parameterchange(self,name):
        pv = yield self.connection.get_server('ParameterVault')
        if name == ('Raman'):
            rm = yield pv.get_parameter(name)
        self.appendPlainText(str(rm['MHz']))

    def defineRegexPatterns(self):
        self.channelpattern = r'Channel\s+([aA0-zZ9]+)\s'
        self.pulsepattern   = r'([a-z]*)\s+([+-]?[0-9]+|var\s+[aA0-zZ9]+)\s+([aA-zZ]+)'
        self.looppattern    = r'#repeat\s+([0-9]+)\s+(.+?\s)\s*#endrepeat'
        self.defpattern     = r'#def\s+(.+?)\s*#enddef'
        self.modepattern    = r'in\s+mode\s+([aA-zZ]+)'

    def parseDefine(self,listofstrings):
        for defblock in listofstrings:
            for line in defblock.strip().split('\n'):
                if '=' in line:
                    line = re.sub('var','',line)
                    exec('self.'+line.strip())
                else:
                    line = line.split()[1].strip() # remove the var part of var A0
                    exec('self.'+line+' = 0.0')

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

if __name__=="__main__":
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = writingwidget(reactor)
    widget.show()

    reactor.run()