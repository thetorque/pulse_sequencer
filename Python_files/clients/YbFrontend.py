from PyQt4 import QtGui
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvasQTAgg
import matplotlib.pyplot as plt
from graphingwidget import graphingwidget
from writingwidget import writingwidget
from SWITCH_CONTROL import switchWidget
from DDS_CONTROL import DDS_CONTROL
from LINETRIGGER_CONTROL import linetriggerWidget


class mainwindow(QtGui.QMainWindow):
    def __init__(self,reactor, parent=None):
        super(mainwindow,self).__init__()
        self.reactor = reactor
        self.connect_labrad()

    @inlineCallbacks
    def connect_labrad(self):
        from connection import connection
        cxn = connection()
        yield cxn.connect()
        self.connection = cxn
        self.create_layout()

    def create_layout(self):
        controlwidget = self.makeControlWidget()
        sequencewidget = self.makeSequenceWidget()

        centralwidget = QtGui.QWidget()
        tabwidget = QtGui.QTabWidget()

        tabwidget.addTab(controlwidget,'Controls')
        tabwidget.addTab(sequencewidget,'Sequence')



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
        #layout.addWidget(switchWidget(self.reactor,self.connection))
        #layout.addWidget(DDS_CONTROL(self.reactor,self.connection))
        widget.setLayout(layout)
        return widget

    def makeSequenceWidget(self):
        widget = QtGui.QWidget()
        from graphingwidget import graphingwidget
        from writingwidget import writingwidget

        layout = QtGui.QHBoxLayout()
        graphing = graphingwidget(self.reactor,self.connection)
        writing = writingwidget(self.reactor,self.connection)
        writing.parsed_trigger.connect(graphing.draw_sequence)
        writing.parsed_trigger.connect(self.program_sequence)

        layout.addWidget(writing)
        layout.addWidget(graphing)
        widget.setLayout(layout)
        return widget

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
        server = yield self.connection.get_server('Pulser')
        yield server.new_sequence()
        yield server.add_dds_standard_pulses(sequence)
        yield server.program_sequence()

    def closeEvent(self,event):
        #reply = QtGui.QMessageBox.question(self, 'Message',
         #       "Are you sure you want to quit?", QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
        #        QtGui.QMessageBox.No)

        #if reply == QtGui.QMessageBox.Yes:
        self.reactor.stop()
          #  event.accept()
        #else:
        #    event.ignore()


if __name__== '__main__':
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = mainwindow(reactor)
    widget.show()
    reactor.run()