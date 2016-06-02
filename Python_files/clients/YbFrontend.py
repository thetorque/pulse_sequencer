from PyQt4 import QtGui
from PyQt4 import QtCore
from PyQt4.QtCore import pyqtSignal
from twisted.internet.defer import inlineCallbacks, Deferred
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvasQTAgg
import matplotlib.pyplot as plt
from SWITCH_CONTROL import switchWidget
from DDS_CONTROL import DDS_CONTROL
from LINETRIGGER_CONTROL import linetriggerWidget
from LEDindicator import LEDindicator
from PyQt4.QtCore import QThread, QObject
from parsingworker import ParsingWorker

class mainwindow(QtGui.QMainWindow):
    start_signal = pyqtSignal()
    stop_signal = pyqtSignal()
    

    def __init__(self,reactor, parent=None):
        super(mainwindow,self).__init__()
        self.reactor = reactor
        d = Deferred()
        d.addCallback(self.connect_labrad)
        d.addCallback(lambda ignored: self.create_layout())
        d.addCallback(lambda ignored: self.setupListeners())
        d.callback("self")



        self.RUNNING = False

    @inlineCallbacks
    def connect_labrad(self,r):
        from connection import connection
        cxn = connection()
        yield cxn.connect()
        self.connection = cxn
        self.context = cxn.context()
        


    def create_layout(self):
        controlwidget = self.makeControlWidget()
        sequencewidget = self.makeSequenceWidget()
        centralwidget = QtGui.QWidget()
        tabwidget = QtGui.QTabWidget()

        tabwidget.addTab(sequencewidget,'Sequence')
        tabwidget.addTab(controlwidget,'Controls')

        layout = QtGui.QHBoxLayout(self)
        layout.addWidget(tabwidget)
        centralwidget.setLayout(layout)

        self.setWindowTitle('Frontend')
        self.create_menubar()
        self.statusBar().showMessage('Ready')
        self.setCentralWidget(centralwidget)
        print "layout done"

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
        #    print e
        widget.setLayout(layout)
        return widget

    def makeSequenceWidget(self):
        widget = QtGui.QWidget()
        string = "#def\n"+"test = PumpFreq from ParameterVault\n"+"#enddef\n"+"\n"+"#def\n"+"T_start = 10\n"+"#enddef\n"
        string +="\n"+"#repeat i=0,i<1,i+1\n"+"\n"+"Channel DDS_2 do 0.1  MHz with  10 dBm for PumpFreq ms at (100+4*i) ms in mode Normal\n"
        string +="\n"+"#endrepeat\n\n\n"+"Channel DDS_2 do 0.1  MHz with 10 dBm for var T_start ms at 40 ms in mode Normal\n"
     
        from graphingwidget import graphingwidget

        self.graphingwidget = graphingwidget(self.reactor,self.connection)
        self.writingwidget = QtGui.QTextEdit('Writingbox')
        self.writingwidget.setPlainText(string)
        self.filename = None
        self.my_thread = QThread()
        self.parsingworker = ParsingWorker(self.reactor,
                                           self.connection,
                                           str(self.writingwidget.toPlainText()))
        self.parsingworker.connectedsignal =False
        self.parsingworker.moveToThread(self.my_thread)
        self.my_thread.start()

        '''
        import __builtin__
        __builtin__.__dict__.update(locals())
        import numpy as np
        print "timing:"
        t = timeit.Timer('self.writing.on_parse()')
        print np.mean(t.repeat(10,10))/.10
        '''
        
        buttonpanel = self.makeButtonPanel()
        filepanel = self.makeFilePanel()
        self.parsingworker.busy.connect(self.ledprogramming.setOn)
        self.parsingworker.finished.connect(self.ledprogramming.setOff)
        self.parsingworker.trackingparameterserver.connect(self.ledtracking.set)
        layout = QtGui.QGridLayout()
        layout.addWidget(buttonpanel,0,0)
        layout.addWidget(filepanel,1,0)
        layout.addWidget(self.writingwidget, 2,0,6,1)
        layout.addWidget(self.graphingwidget, 0,1,7,1)
        widget.setLayout(layout)
        
        return widget

    def makeFilePanel(self):
        panel = QtGui.QToolBar()
        panel.addAction(QtGui.QIcon('icons/document-open.svg'),'open',self.openbuttonclick)
        panel.addAction(QtGui.QIcon('icons/document-save.svg'),'save',self.savebuttonclick)
        panel.addAction(QtGui.QIcon('icons/document-save-as.svg'),'save as',self.saveasbuttonclick)
        panel.addAction(QtGui.QIcon('icons/document-new.svg'),'new',self.newbuttonclick)

        return panel
    
    def openbuttonclick(self):
        if self.writingwidget.document().isModified():
            reply = QtGui.QMessageBox.question(self, 'Message',
                "Do you want to save the changes?", QtGui.QMessageBox.Yes | QtGui.QMessageBox.No | QtGui.QMessageBox.Cancel,
                QtGui.QMessageBox.Cancel)
            if reply == QtGui.QMessageBox.Cancel:
                return
            else:
                if reply == QtGui.QMessageBox.Yes:
                    self.savebuttonclick()
                fname = QtGui.QFileDialog.getOpenFileName(self, 'Open file','sequencescripts/','*.txt')
                self.filename=fname
                try:
                    with open(fname,'r') as f:
                        self.writingwidget.setPlainText(f.read())
                except Exception,e:
                    print e
        

    def savebuttonclick(self):
        if self.filename is None:
            self.saveasbuttonclick()
        else:
            self.save()
            

    def saveasbuttonclick(self):
        defname = self.filename if self.filename is not None else "script.txt"
        sname = QtGui.QFileDialog.getSaveFileName(self,'Save file','sequencescripts/'+defname,'*.txt')
        self.filename=sname
        self.save()

    def save(self):
        try:
            with open(self.filename,'w') as f:
                f.write(self.writingwidget.toPlainText())
        except Exception,e:
            print e

    def newbuttonclick(self):
        if self.writingwidget.document().isModified():
            reply = QtGui.QMessageBox.question(self, 'Message',
                "Do you want to save the changes?", QtGui.QMessageBox.Yes | QtGui.QMessageBox.No | QtGui.QMessageBox.Cancel,
                QtGui.QMessageBox.Cancel)
            if reply == QtGui.QMessageBox.Cancel:
                return
            else:
                if reply == QtGui.QMessageBox.Yes:
                    self.savebuttonclick()
                self.writingwidget.clear()
                self.filename=None    



    def makeButtonPanel(self):
        panel = QtGui.QWidget()
        Startbutton = QtGui.QPushButton(QtGui.QIcon('icons/go-next.svg'),'RUN')
        Stopbutton = QtGui.QPushButton(QtGui.QIcon('icons/emblem-noread.svg'),'STOP')
        LineTrigbutton = QtGui.QPushButton('linetrig')
        LineTrigbutton.setCheckable(True)
        state = False
        LineTrigbutton.setChecked(state)
        LineTrigbutton.pressed.connect(self.toggle_linetrig)
        
        self.ledrunning = LEDindicator('Running')
        self.ledprogramming = LEDindicator('Prog.')
        self.ledlinetrigger = LEDindicator('Ext trig')
        self.ledtracking = LEDindicator('Listening to Param')
        Startbutton.pressed.connect(self.on_Start)
        Stopbutton.pressed.connect(self.on_Stop)
        Spacetaker = QtGui.QWidget()
        layout = QtGui.QGridLayout()
        layout.addWidget(Startbutton,0,0,2,2)
        layout.addWidget(Stopbutton,2,0,2,2)
        layout.addWidget(self.ledrunning,0,3,2,1)
        layout.addWidget(self.ledprogramming,0,4,2,1)
        layout.addWidget(self.ledlinetrigger,0,5,2,1)
        layout.addWidget(self.ledtracking,0,6,2,1)
        layout.addWidget(LineTrigbutton,2,5,1,1)
        layout.addWidget(Spacetaker,0,7,4,5)
        layout.setSpacing(1)
        layout.setMargin(1)
        panel.setLayout(layout)
        return panel

    def on_Start(self):
        if not self.parsingworker.connectedsignal:
            self.parsingworker.parsed_trigger.connect(self.graphingwidget.plottingworker.run)
            self.parsingworker.connectedsignal =True
        self.parsingworker.add_text(str(self.writingwidget.toPlainText()))
        self.parsingworker.start.emit()

    def on_Stop(self):
        self.RUNNING = False
        self.stop_signal.emit()
        
    @inlineCallbacks
    def toggle_linetrig(self):
        state = self.sender().isChecked()
        server = yield self.connection.get_server('Pulser')
        yield server.line_trigger_state(state)

    def create_menubar(self):
        menubar = self.menuBar()

        exitAction = QtGui.QAction(QtGui.QIcon('exit.png'), '&Exit', self)
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(self.closeEvent)
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(exitAction)

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
            yield p.start_number(1)
            yield p.wait_sequence_done()
        yield p.stop_sequence()
        self.ledrunning.setOff()

    @inlineCallbacks
    def setupListeners(self):
        SIGNALID = 115687
        server = yield self.connection.get_server('Pulser')
        yield server.signal__new_line_trigger_parameter(SIGNALID)
        yield server.addListener(listener = self.line_trigger_signal,
                                 source = None,
                                 ID = SIGNALID,
                                 context=self.context)
        server = yield self.connection.get_server('ParameterVault')
        yield server.signal__parameter_change(SIGNALID+10)
        yield server.addListener(listener = self.parsingworker.update_parameters,
                                 ID = SIGNALID+10)
        print "setup done"
        
    def line_trigger_signal(self,x, (state,duration)):
        if state:
            self.ledlinetrigger.setOn()
        else:
            self.ledlinetrigger.setOff()


    def parameter_change(self,signal,info):
        print "got signal"
        collection, name = info
        print collection,name
        self.parsingworker.update_parameters(collection,name)


if __name__== '__main__':
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = mainwindow(reactor)
    widget.show()
    reactor.run()