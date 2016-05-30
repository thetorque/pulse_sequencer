from twisted.internet.defer import inlineCallbacks
from PyQt4 import QtGui
from PyQt4.QtCore import pyqtSignal

SIGNALID = 489136

class writingwidget(QtGui.QWidget):
    parsed_trigger = pyqtSignal(list)

    def __init__(self,reactor, connection =None, parent= None):
        super(writingwidget,self).__init__()
        self.reactor = reactor
        self.connection = connection
        self.setupLayout()


    def setupLayout(self):
        layout=QtGui.QVBoxLayout(self)
        self.textedit = QtGui.QTextEdit()
        string = "'Raman_rad', WithUnit(0.1, 'ms'), WithUnit(999.9, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0 \n"
        string +=  "'Raman_ax', WithUnit(1000, 'ms'), WithUnit(3000, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0 \n"
        string +=  "'Raman_rad', WithUnit(1002, 'ms'), WithUnit(3000, 'ms'), WithUnit(85.0, 'MHz'), WithUnit(-20.0, 'dBm'), WithUnit(0.0,'deg'),WithUnit(0,'MHz'),WithUnit(0,'dBm'),0   \n"
       
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
        from labrad.units import WithUnit
        sequence = []
        text = str(self.textedit.toPlainText())
        lines = text.split('\n')
        for line in lines:
            #line = line.strip()
            col = line.split(',')
            if len(col)>13:
                sequence.append((eval(col[0]),
                                 eval(col[1]+','+col[2]),
                                 eval(col[3]+','+col[4]),
                                 eval(col[5]+','+col[6]),
                                 eval(col[7]+','+col[8]),
                                 eval(col[9]+','+col[10]),
                                 eval(col[11]+','+col[12]),
                                 eval(col[13] + ',' + col[14]),
                                 eval(col[15])))
        self.parsed_trigger.emit(sequence)

    @inlineCallbacks
    def on_parameterchange(self,name):
        pv = yield self.connection.get_server('ParameterVault')
        if name == ('Raman'):
            rm = yield pv.get_parameter(name)
        self.appendPlainText(str(rm['MHz']))

if __name__=="__main__":
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = writingwidget(reactor)
    widget.show()

    reactor.run()