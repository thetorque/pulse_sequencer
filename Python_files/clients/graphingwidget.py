from PyQt4 import QtGui
from PyQt4.QtCore import QThread, pyqtSignal
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
import numpy as np
import time
from PyQt4.QtCore import QThread, pyqtSignal
from connection import connection
from plottingworker import PlottingWorker

class graphingwidget(QtGui.QWidget):

    SIGNALID = 104692
    update_signal = pyqtSignal(list)
    def __init__(self,reactor, cnx):
        super(graphingwidget,self).__init__()
        self.reactor = reactor
        self.connection = cnx
        self.initialize()


    @inlineCallbacks
    def initialize(self):
        server = yield self.connection.get_server('Pulser')
        channellist = yield server.get_dds_channels()

        self.do_layout(channellist)


    def do_layout(self,channellist):
        self.setGeometry(100,100,850,550)
        self.setWindowTitle('Graphical representation')
        self.figure = plt.figure(0,(5,5))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.mpl_connect('motion_notify_event',self.update_tooltip)
        self.layoutVertical = QtGui.QVBoxLayout(self)
        self.layoutVertical.addWidget(self.canvas)
        


        axlist = {}
        for i in range(len(channellist)):
            axlist[channellist[i]] = self.figure.add_subplot(16,1,i+1)

        for anax in axlist.values():
            anax.axes.get_xaxis().set_ticks([])
            anax.get_yaxis().set_ticks([])
            anax.set_ylim(0,1.5)
        self.channel_ax_list = axlist

        self.plottingthread = QThread()
        self.plottingworker = PlottingWorker((self.channel_ax_list))
        self.plottingworker.plotted_trigger.connect(self.update)
        self.plottingworker.moveToThread(self.plottingthread)
        self.plottingthread.start()

    def update(self):
        self.canvas.draw()

    def update_tooltip(self,event):
        if event.inaxes:
            x = event.xdata
            self.canvas.setToolTip(str(int(x)))

if __name__== '__main__':
    app = QtGui.QApplication( [])
    import qt4reactor
    qt4reactor.install()
    from twisted.internet import reactor
    widget = graphingwidget(reactor)

    widget.show()
    
    reactor.run()