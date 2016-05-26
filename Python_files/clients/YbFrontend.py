from PyQt4 import QtGui
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvasQTAgg
import matplotlib.pyplot as plt
from graphingwidget import graphingwidget
from writingwidget import writingwidget


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
        centralwidget = QtGui.QWidget()
        layout = QtGui.QHBoxLayout(self)

        graphing = graphingwidget(self.reactor,self.connection)
        writing = writingwidget(self.reactor)
        writing.parsed_trigger.connect(graphing.draw_sequence)
        writing.parsed_trigger.connect(self.program_sequence)

        self.setWindowTitle('Frontend')
        self.create_menubar()
        self.statusBar().showMessage('Ready')
        layout.addWidget(writing)
        layout.addWidget(graphing)
        centralwidget.setLayout(layout)
        self.setCentralWidget(centralwidget)

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
        yield server.add_dds_pulses(sequence)
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