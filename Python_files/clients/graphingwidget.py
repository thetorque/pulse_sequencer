from PyQt4 import QtGui
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
import numpy as np
import time

class graphingwidget(QtGui.QWidget):

    SIGNALID = 104692

    def __init__(self,reactor, cnx = None, parent=None):
        super(graphingwidget,self).__init__()
        self.reactor = reactor
        self.cnx = cnx
        self.connect_labrad()
#        self.plot_test()

    @inlineCallbacks
    def connect_labrad(self):
        from labrad import types as T
        self.T = T
        if self.cnx is None:
            from connection import connection
            self.cnx = connection()
            yield self.cnx.connect()
        try:
            from labrad.types import Error
            self.Error = Error
            yield self.initialize()
        except Exception, e:
            print e
            print 'Pulser not available'

    @inlineCallbacks
    def initialize(self):
        server = yield self.cnx.get_server('Pulser')
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

    def draw_sequence(self,sequence):
        print "starting drawing"
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


        self.make_nicer(lastend,frequencies,amplitudes)
        self.canvas.draw()

    def make_nicer(self,lastend,freq,amp):
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