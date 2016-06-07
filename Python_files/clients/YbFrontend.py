from PyQt4 import QtGui
from PyQt4 import QtCore
from PyQt4.QtCore import pyqtSignal,QThread, QObject, QEventLoop, QWaitCondition, QTimer
from twisted.internet.defer import inlineCallbacks, Deferred
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvasQTAgg
import matplotlib.pyplot as plt
from SWITCH_CONTROL import switchWidget
from DDS_CONTROL import DDS_CONTROL
from LINETRIGGER_CONTROL import linetriggerWidget
from LEDindicator import LEDindicator
from parsingworker import ParsingWorker
from pulserworker import PulserWorker
import time

class mainwindow(QtGui.QMainWindow):
    start_signal = pyqtSignal()
    stop_signal = pyqtSignal()
    

    def __init__(self,reactor, parent=None):
        super(mainwindow,self).__init__()
        self.reactor = reactor
        self.initialize()
        self.ParamID = None


    # This is a seperate function because it needs to 
    # be able to yield, and __init__ cannot do that
    @inlineCallbacks
    def initialize(self):
        yield self.connect_labrad()
        yield self.create_layout()
        self.messageout('Layout done')
        yield self.get_parameters()
        self.start_parserthread()
        self.start_pulserthread()
        self.messageout('Parserthread started')
        self.fill_parameterstree()
        self.setupListeners()
        self.messageout('Listeners setup')
        self.messageout('-------------------')
        self.messageout('Initialization done')
        

        self.RUNNING = False

    @inlineCallbacks
    def connect_labrad(self):
        from connection import connection
        cxn = connection()
        yield cxn.connect()
        self.connection = cxn
        self.context = cxn.context()
       

########################################################################
#########                                                      #########
#########               Creating the GUI                       #########
#########                                                      #########
########################################################################
    
    #################
    # Central (main window)
    #################
    def create_layout(self):
        controlwidget = self.makeControlWidget()
        sequencewidget = self.makeSequenceWidget()
        parameterswidget = self.makeParameterWidget()
        centralwidget = QtGui.QWidget()
        tabwidget = QtGui.QTabWidget()

        tabwidget.addTab(sequencewidget,'Sequence')
        tabwidget.addTab(controlwidget,'Controls')
        tabwidget.addTab(parameterswidget,'Parameters')

        layout = QtGui.QHBoxLayout(self)
        layout.addWidget(tabwidget)
        centralwidget.setLayout(layout)

        self.setWindowTitle('Frontend')
        self.create_menubar()
        self.statusBar().showMessage('Ready')
        self.setCentralWidget(centralwidget)

    def create_menubar(self):
        menubar = self.menuBar()

        exitAction = QtGui.QAction(QtGui.QIcon('exit.png'), '&Exit', self)
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(self.closeEvent)
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(exitAction)

    def closeEvent(self,event):
        self.reactor.stop()
  

    #################
    # Control tab panel
    #################
    def makeControlWidget(self):
        widget = QtGui.QWidget()
        from SWITCH_CONTROL import switchWidget
        from DDS_CONTROL import DDS_CONTROL
        from LINETRIGGER_CONTROL import linetriggerWidget

        layout = QtGui.QVBoxLayout()
        try:
            layout.addWidget(switchWidget(self.reactor,self.connection))
            layout.addWidget(DDS_CONTROL(self.reactor,self.connection))
            #layout.addWidget(linetriggerWidget(self.reactor,self.connection))
        except AttributeError, e:
            print e
        widget.setLayout(layout)
        return widget

    #################
    # Parameter tab panel
    #################
    def makeParameterWidget(self):
        widget = QtGui.QWidget()
        self.parametertree = QtGui.QTreeWidget()
        self.parametertree.setColumnCount(2)
        self.parametertree.header().setResizeMode(0,QtGui.QHeaderView.ResizeToContents)
        self.parametertree.header().setResizeMode(1,QtGui.QHeaderView.ResizeToContents)
        layout = QtGui.QHBoxLayout()
        layout.addWidget(self.parametertree)
        widget.setLayout(layout)
        return widget

    #################
    # Sqeuence tab panel
    #################
    def makeSequenceWidget(self):
        from graphingwidget import graphingwidget
        self.filename = None
        splitterwidget = QtGui.QSplitter()
        string = "#def\n"+"tstart = 10\n"+"#enddef\n"
        string += "Channel DDS_2 do 10  MHz with -10 dBm for var tstart ms at 40 ms in mode Normal\n"
        
        self.graphingwidget = graphingwidget(self.reactor,self.connection)
        self.writingwidget = QtGui.QTextEdit('Writingbox')
        self.writingwidget.setPlainText(string)

        leftwidget=QtGui.QWidget()
        buttonpanel = self.makeButtonPanel()
        leftlayout = QtGui.QGridLayout()
        leftlayout.addWidget(buttonpanel,0,0)
        leftlayout.addWidget(self.writingwidget, 1,0,4,1)
        leftwidget.setLayout(leftlayout)


        splitterwidget.addWidget(leftwidget)
        splitterwidget.addWidget(self.graphingwidget)
        return splitterwidget

    def makeButtonPanel(self):
        panel = QtGui.QWidget()
        Startbutton = QtGui.QPushButton(QtGui.QIcon('icons/go-next.svg'),'RUN')
        Stopbutton = QtGui.QPushButton(QtGui.QIcon('icons/emblem-noread.svg'),'STOP')
        LineTrigbutton = QtGui.QPushButton('linetrig')
        LineTrigbutton.setCheckable(True)
        state = True
        LineTrigbutton.setChecked(state)
        LineTrigbutton.pressed.connect(self.toggle_linetrig)
        self.ledrunning = LEDindicator('Running')
        self.ledprogramming = LEDindicator('Prog.')
        self.ledlinetrigger = LEDindicator('Ext trig')
        self.ledtracking = LEDindicator('Listening to Param')
        self.ledparsing = LEDindicator('Parse')

        filetoolbar = QtGui.QToolBar()
        filetoolbar.addAction(QtGui.QIcon('icons/document-open.svg'),'open',self.openbuttonclick)
        filetoolbar.addAction(QtGui.QIcon('icons/document-save.svg'),'save',self.savebuttonclick)
        filetoolbar.addAction(QtGui.QIcon('icons/document-new.svg'),'new',self.newbuttonclick)

        self.Messagebox = QtGui.QTextEdit()
        self.Messagebox.setReadOnly(True)
        font = self.Messagebox.font()
        font.setFamily("courier")
        font.setPointSize(10)

        Startbutton.pressed.connect(self.on_Start)
        Stopbutton.pressed.connect(self.on_Stop)
        Spacetaker = QtGui.QWidget()
        ledpanel =QtGui.QWidget()
        ledlayout = QtGui.QHBoxLayout()
        ledlayout.setMargin(0)
        ledlayout.setSpacing(0)
        ledlayout.addWidget(self.ledrunning)
        ledlayout.addWidget(self.ledprogramming)
        ledlayout.addWidget(self.ledparsing)
        ledlayout.addWidget(self.ledlinetrigger)
        ledlayout.addWidget(self.ledtracking)
        ledpanel.setLayout(ledlayout)
        layout = QtGui.QGridLayout()
        layout.addWidget(Startbutton,0,0)
        layout.addWidget(Stopbutton,1,0)
        layout.addWidget(ledpanel,0,1,1,5)
        layout.addWidget(LineTrigbutton,1,1)
        layout.addWidget(filetoolbar,2,0,1,2)
        layout.addWidget(self.Messagebox,1,2,2,4)
        panel.setLayout(layout)
        return panel

########################################################################
#########                                                      #########
#########                   Start parsers                      #########
#########                and connect signals                   #########
#########                                                      #########
########################################################################
    def start_parserthread(self):
        self.parsingthread = QThread()
        self.parsingworker = ParsingWorker(str(self.writingwidget.toPlainText()),self.reactor,self.connection,self.context)
        self.parsingworker.moveToThread(self.parsingthread)
        self.parsingworker.busy_trigger.connect(self.ledparsing.setState)
        self.parsingworker.trackingparameterserver.connect(self.ledtracking.setState)
        self.parsingworker.parsermessages.connect(self.messageout)
        #self.parsingworker.parsing_done_trigger.connect(self.done_parsing)
        self.parsingworker.parsing_done_trigger.connect(self.graphingwidget.plottingworker.run)
        self.parsingthread.start()
        self.parsingworker.set_parameters(self.parameters)

    def start_pulserthread(self):
        self.pulserthread = QThread()
        self.pulserworker = PulserWorker(self.reactor,self.connection,self.parsingworker)
        self.pulserworker.moveToThread(self.pulserthread)
        self.pulserworker.pulsermessages.connect(self.messageout)
        self.parsingworker.binary_trigger.connect(self.pulserworker.new_binary_sequence)
        self.pulserworker.sequence_done_trigger.connect(self.sendIdtoParameterVault)
        self.pulserthread.start()
        
        self.pulserworker.set_shottime(2) #cycletime of operation

    @inlineCallbacks
    def setupListeners(self):
        SIGNALID = 115687
        pv = yield self.connection.get_server('ParameterVault')
        yield pv.signal__parameter_change(SIGNALID+10)
        yield pv.addListener(listener = self.parameter_change,
                                 ID = SIGNALID+10)

    def fill_parameterstree(self):
        self.parametertree.clear()
        self.fill_item(self.parametertree.invisibleRootItem(), self.parameters)

    def fill_item(self,item, value):
        item.setExpanded(False)
        if type(value) is dict:
            for key, val in sorted(value.iteritems()):
                child = QtGui.QTreeWidgetItem()
                child.setText(0, unicode(key))
                item.addChild(child)
                self.fill_item(child, val)
        else:
            item.setText(1, unicode(value))

        
########################################################################
#########                                                      #########
#########                Signal and Callback                   #########
#########                     handling                         #########
#########                                                      #########
######################################################################## 
    
    #################
    #Deliveres a message to the logbox
    #################   
    def messageout(self,text):
        stamp = time.strftime('%H:%M:%S')
        self.Messagebox.moveCursor(QtGui.QTextCursor.End)
        self.Messagebox.insertPlainText("\n"+stamp+" - "+text)
        self.Messagebox.moveCursor(QtGui.QTextCursor.End)

    @inlineCallbacks
    def done_parsing(self,sequence,parameterID):
        self.ledprogramming.setOn()
        #server = yield self.connection.get_server('Pulser')
        #try:
        #    yield server.stop_sequence()
        #except Exception,e:
        #    self.parsermessages('DEBUG: Program sequence \n'+ repr(e))
        #yield server.new_sequence()
        #yield server.add_dds_standard_pulses(self.sequence)
        #yield server.program_sequence()
        self.ledprogramming.setOff()
        #self.sendIdtoParameterVault(parameterID)
        #self.run_sequence()

    
    #################
    #Line triggering
    #################    
    @inlineCallbacks
    def toggle_linetrig(self):
        state = self.sender().isChecked()
        server = yield self.connection.get_server('Pulser')
        yield server.line_trigger_state(state)
        if state:
            self.ledlinetrigger.setOn()
        else:
            self.ledlinetrigger.setOff()

    #################
    #Parameter change on the parameter server
    #send it on on the parsingthread
    #and update the parameter editor
    #################

    @inlineCallbacks
    def parameter_change(self,signal,info):
        collection, name = info
        pv = yield self.connection.get_server('ParameterVault')
        val = yield pv.get_parameter(collection,name)
        self.parsingworker.update_parameters(collection,name,val)
    
        self.parameters[collection][name] = val
        try:
            treeitem = self.parametertree.findItems(name,QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)[0]
            treeitem.setText(1,str(val))
        except Exception, e:
            self.messageout('DEBUG Parameter Change: \n' + repr(e))
        self.messageout('New Value from Parameter Vault\n {:} = {:}'.format(name,val))


    @inlineCallbacks
    def get_parameters(self):
        try:
            pv = yield self.connection.get_server('ParameterVault')
            coldict = {}
            collections = yield pv.get_collections()
            for acol in collections:
                coldict[acol] = {}
                names = yield pv.get_parameter_names(acol)
                for aname in names:
                    coldict[acol][aname] = yield pv.get_parameter(acol,aname)
            self.parameters = coldict
        except Exception, e:
            print repr(e)
        
    @inlineCallbacks
    def sendIdtoParameterVault(self,intID):
        self.paramID = intID
        pv = yield self.connection.get_server('ParameterVault')
        yield pv.set_parameter('shotID','PulserProgrammed',intID)
        self.messageout('Completed shot: {:}'.format(intID))

        

########################################################################
#########                                                      #########
#########                BUTTON ACTIONS                        #########
#########                                                      #########
########################################################################


    #################
    #Start and stop buttons
    #################
    def on_Start(self):
        self.parsingworker.add_text(str(self.writingwidget.toPlainText()))
        print 'starting'
        self.parsingworker.start.emit()
        self.pulserworker.startsignal.emit()

    def on_Stop(self):
        self.parsingworker.Parsing = False
        self.stop_signal.emit()
        self.pulserworker.stopsignal.emit()


    #########################
    #File buttons
    #########################
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
        if len(fname) != 0:
            try:
                with open(fname,'r') as f:
                    self.writingwidget.setPlainText(f.read())
            except Exception,e:
                print e
        
    def savebuttonclick(self):
        defname = time.strftime('%y%m%d_%H%M%S')
        sname = QtGui.QFileDialog.getSaveFileName(self,'Save file','sequencescripts/'+defname,'*.txt')
        if len(sname)!=0:
            try:
                with open(sname,'w') as f:
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


if __name__== '__main__':
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = mainwindow(reactor)
    widget.showMaximized()
    widget.show()
    reactor.run()