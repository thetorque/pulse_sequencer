from PyQt4 import QtGui
from PyQt4 import QtCore
from PyQt4.QtCore import pyqtSignal
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvasQTAgg
import matplotlib.pyplot as plt
from graphingwidget import graphingwidget
from writingwidget import writingwidget
from SWITCH_CONTROL import switchWidget
from DDS_CONTROL import DDS_CONTROL
from LINETRIGGER_CONTROL import linetriggerWidget
from LEDindicator import LEDindicator
import timeit

class mainwindow(QtGui.QMainWindow):
    start_signal = pyqtSignal()
    stop_signal = pyqtSignal()
    SIGNALID = 115687
    def __init__(self,reactor, parent=None):
        super(mainwindow,self).__init__()
        self.reactor = reactor
        self.connect_labrad()
        self.RUNNING = False

    @inlineCallbacks
    def connect_labrad(self):
        from connection import connection
        cxn = connection()
        yield cxn.connect()
        self.connection = cxn
        self.create_layout()
        self.populateParameters()
        self.setupListeners()

    def create_layout(self):
        controlwidget = self.makeControlWidget()
        sequencewidget = self.makeSequenceWidget()
        self.parameditorwidget = self.makeParameterEditorWidget()

        centralwidget = QtGui.QWidget()
        tabwidget = QtGui.QTabWidget()

        tabwidget.addTab(controlwidget,'Controls')
        tabwidget.addTab(sequencewidget,'Sequence')
        tabwidget.addTab(self.parameditorwidget,'Parameters')

        layout = QtGui.QHBoxLayout(self)
        layout.addWidget(tabwidget)
        centralwidget.setLayout(layout)

        self.setWindowTitle('Frontend')
        self.create_menubar()
        self.statusBar().showMessage('Ready')


        self.setCentralWidget(centralwidget)

    def makeControlWidget(self):
        widget = QtGui.QWidget()
        from SWITCH_CONTROL import switchWidget
        from DDS_CONTROL import DDS_CONTROL
        from LINETRIGGER_CONTROL import linetriggerWidget

        layout = QtGui.QVBoxLayout()
        #try:
        #    layout.addWidget(switchWidget(self.reactor,self.connection))
        #    layout.addWidget(DDS_CONTROL(self.reactor,self.connection))
        #    layout.addWidget(linetriggerWidget(self.reactor,self.connection))
        #except AttributeError, e:
        #    pass
        widget.setLayout(layout)
        return widget

    def makeSequenceWidget(self):
        widget = QtGui.QWidget()
        from graphingwidget import graphingwidget
        from writingwidget import writingwidget

        graphing = graphingwidget(self.reactor,self.connection)
        writing = writingwidget(self.reactor,self.connection)
        writing.parsed_trigger.connect(graphing.draw_sequence) #So we make the program_sequence be called first
        writing.parsed_trigger.connect(self.program_sequence) #The order here determines which is called first
        
        '''
        import __builtin__
        __builtin__.__dict__.update(locals())
        import numpy as np
        print "timing:"
        t = timeit.Timer('self.writing.on_parse()')
        print np.mean(t.repeat(10,10))/.10
        '''
        
        self.start_signal.connect(writing.on_parse) 
        buttonpanel = self.makeButtonPanel()
        layout = QtGui.QGridLayout()

        layout.addWidget(buttonpanel,0,0)
        layout.addWidget(writing, 1,0,4,1)
        layout.addWidget(graphing, 0,1,5,1)
        widget.setLayout(layout)
        
        return widget

    def makeButtonPanel(self):
        panel = QtGui.QWidget()
        Startbutton = QtGui.QPushButton('RUN')
        Stopbutton = QtGui.QPushButton('STOP')
        self.ledrunning = LEDindicator('Running')
        self.ledprogramming = LEDindicator('Prog.')
        self.ledlinetrigger = LEDindicator('Ext trig')
        Startbutton.pressed.connect(self.on_Start)
        Stopbutton.pressed.connect(self.on_Stop)
        Spacetaker = QtGui.QWidget()
        layout = QtGui.QGridLayout()
        layout.addWidget(Startbutton,0,0,2,2)
        layout.addWidget(Stopbutton,2,0,2,2)
        layout.addWidget(self.ledrunning,0,3,2,1)
        layout.addWidget(self.ledprogramming,0,4,2,1)
        layout.addWidget(self.ledlinetrigger,0,5,2,1)
        layout.addWidget(Spacetaker,0,6,4,5)
        panel.setLayout(layout)
        return panel

    def on_Start(self):
        self.RUNNING = True
        self.start_signal.emit()

    def on_Stop(self):
        self.RUNNING = False
        self.stop_signal.emit()

    def makeParameterEditorWidget(self):
        widget = QtGui.QWidget()
        from tree_view.Controllers import ParametersEditor
        self.ParametersEditor = ParametersEditor(self.reactor)
        layout = QtGui.QHBoxLayout()
        layout.addWidget(self.ParametersEditor)
        widget.setLayout(layout)
        return widget

    @inlineCallbacks
    def populateParameters(self):
        pv = yield self.connection.get_server('ParameterVault')
        collections = yield pv.get_collections()
        for collection in collections:
            self.ParametersEditor.add_collection_node(collection)
            parameters = yield pv.get_parameter_names(collection)
            for param_name in parameters:
                value = yield pv.get_parameter(collection, param_name, False)
                self.ParametersEditor.add_parameter(collection, param_name, value)

    def create_menubar(self):
        menubar = self.menuBar()

        exitAction = QtGui.QAction(QtGui.QIcon('exit.png'), '&Exit', self)
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(self.closeEvent)
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(exitAction)

    @inlineCallbacks
    def program_sequence(self,sequence):
        self.ledprogramming.setOn()
        server = yield self.connection.get_server('Pulser')
        yield server.new_sequence()
        yield server.add_dds_standard_pulses(sequence)
        yield server.program_sequence()
        self.ledprogramming.setOff()
        #self.run_sequence()

    def closeEvent(self,event):
        #reply = QtGui.QMessageBox.question(self, 'Message',
         #       "Are you sure you want to quit?", QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
        #        QtGui.QMessageBox.No)

        #if reply == QtGui.QMessageBox.Yes:
        self.reactor.stop()
          #  event.accept()
        #else:
        #    event.ignore()
    @inlineCallbacks
    def run_sequence(self):
        self.ledrunning.setOn()
        p = yield self.connection.get_server('Pulser')
        while self.RUNNING:
            p.start_number(1)
            p.wait_sequence_done()
        p.stop_sequence()
        self.ledrunning.setOff()

    @inlineCallbacks
    def setupListeners(self):
        server = yield self.connection.get_server('Pulser')
        yield server.signal__new_line_trigger_parameter(self.SIGNALID)
        yield server.addListener(listener = self.line_trigger_signal, source = None, ID = self.SIGNALID)

    def line_trigger_signal(self,x, (state,duration)):
        if state:
            self.ledlinetrigger.setOn()
        else:
            self.ledlinetrigger.setOff()


if __name__== '__main__':
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = mainwindow(reactor)
    widget.show()
    reactor.run()