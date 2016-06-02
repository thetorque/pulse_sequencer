from PyQt4 import QtGui
from PyQt4.QtCore import QThread, pyqtSignal, pyqtSlot, QObject
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
import numpy as np
from connection import connection

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
        self.plottingthread = QThread()
        self.plottingworker = PlottingWorker()
        self.plottingworker.plotted_trigger.connect(self.update)
        self.plottingworker.moveToThread(self.plottingthread)
        self.plottingthread.start()
        
        self.do_layout(channellist)


    def do_layout(self,channellist):
        self.figure = plt.figure(0,(5,5))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.mpl_connect('motion_notify_event',self.update_tooltip)
        self.layoutVertical = QtGui.QVBoxLayout(self)
        self.layoutVertical.addWidget(self.canvas)
        


        axlist = {}

        for i in range(len(channellist)):
            axlist[channellist[i]] = self.figure.add_subplot(16,1,i+1)

        for name,anax in axlist.iteritems():
            anax.axes.get_xaxis().set_ticks([])
            anax.get_yaxis().set_ticks([])
            anax.set_ylim(0,1.5)
            anax.text(-0.01, 0.5,name, horizontalalignment='right',
                                                 verticalalignment='center',
                                              transform=anax.transAxes)
        self.figure.subplots_adjust(left=0.2,right=0.995,top=0.99,bottom=0.01)
        self.channel_ax_list = axlist
        self.plottingworker.setup_axes(axlist)
        

    def update(self):
        self.canvas.draw()

    def update_tooltip(self,event):
        if event.inaxes:
            x = event.xdata
            self.canvas.setToolTip(str(int(x)))

class PlottingWorker(QObject):
    plotted_trigger= pyqtSignal()
    start = pyqtSignal(list)
    def __init__(self):
        super(PlottingWorker,self).__init__()
        self.thread_channel_ax_list = None
        self.start.connect(self.run)

    def setup_axes(self,axlist):
        self.thread_channel_ax_list = axlist

    def do_sequence(self,sequence):
        lastend = 0
        for achannelname, achannelax in self.thread_channel_ax_list.iteritems():
            channelpulses = [i for i in sequence if i[0] == achannelname]
            channelpulses.sort(key= lambda name: name[1]['ms'])
            starttimes = []
            endtimes = []
            frequencies = []
            amplitudes = []
            for apulse in channelpulses:
                starttimes.append(apulse[1]['ms'])
                endtimes.append((apulse[1]+ apulse[2])['ms'])
                frequencies.append(apulse[3]['MHz'])
                amplitudes.append(apulse[4]['dBm'])

            xdata = [0]
            ydata = [0]
            for i in range(len(starttimes)):
                xdata += [starttimes[i]]*2 + [endtimes[i]]*2
                               
                if ydata[-1] == 0:
                    ydata += [0,1,1,0]
                else:
                    ydata += [1,0,0,1]

            lastend = int(xdata[-1]) if lastend<xdata[-1] else lastend

            achannelax.clear()
            achannelax.plot(xdata,ydata)


        minorLocator = AutoMinorLocator()

        for i in range(len(self.thread_channel_ax_list)):
            achannelax = self.thread_channel_ax_list.values()[i]
            name = self.thread_channel_ax_list.keys()[i]
            achannelax.set_ylim(0,1.5)
            achannelax.set_xlim(0,lastend)
            achannelax.get_yaxis().set_ticks([])
            achannelax.get_xaxis().set_minor_locator(minorLocator)
            achannelax.get_xaxis().grid(True,which='both')
            achannelax.text(-0.01, 0.5,name, horizontalalignment='right',
                                                 verticalalignment='center',
                                              transform=achannelax.transAxes)
            if i < (len(self.thread_channel_ax_list)-1):
                achannelax.get_xaxis().set_ticklabels([])
    
    @pyqtSlot(list)
    def run(self,sequence):
        self.do_sequence(sequence)
        self.plotted_trigger.emit()
