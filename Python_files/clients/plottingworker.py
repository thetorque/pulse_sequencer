from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot
from twisted.internet.defer import inlineCallbacks

from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
import numpy as np
from connection import connection

class PlottingWorker(QObject):
    plotted_trigger= pyqtSignal()
    start = pyqtSignal(list)
    def __init__(self,axlist):
        super(PlottingWorker,self).__init__()
        self.channel_ax_list = axlist
        self.start.connect(self.run)

    def do_sequence(self,sequence):
        lastend = 0
        for achannelname, achannelax in self.channel_ax_list.iteritems():
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

        for i in range(len(self.channel_ax_list)):
            achannelax = self.channel_ax_list.values()[i]
            achannelax.set_ylim(0,1.5)
            achannelax.set_xlim(0,lastend)
            achannelax.get_yaxis().set_ticks([])
            achannelax.get_xaxis().set_minor_locator(minorLocator)
            achannelax.get_xaxis().grid(True,which='both')
            if i < (len(self.channel_ax_list)-1):
                achannelax.get_xaxis().set_ticklabels([])
    
    @pyqtSlot(list)
    def run(self,sequence):
        self.do_sequence(sequence)
        self.plotted_trigger.emit()


