from PyQt4 import QtGui
from twisted.internet.defer import inlineCallbacks
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import numpy as np

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
        sequence.sort(key= lambda name: name[0])
        lastend = 0
        for achannelname, achannelax in self.channel_ax_list.iteritems():
            channelpulses = [i for i in sequence if i[0] == achannelname]
            sequence.sort(key= lambda name: name[1]['ms'])
            starttimes = []
            endtimes = []
            frequencies = []
            amplitudes = []
            for apulse in channelpulses:
                starttimes.append(apulse[1]['ms'])
                endtimes.append((apulse[1]+ apulse[2])['ms'])
                frequencies.append(apulse[3]['MHz'])
                amplitudes.append(apulse[4]['dBm'])
            try:
                lastend = endtimes[-1] if endtimes[-1]>lastend else lastend
            except IndexError as e:
                pass

            xdata = [0]
            ydata = [0]
            xdata = xdata + [val for val in starttimes+endtimes for n in (0,1)]
            for i in range(1,len(xdata),2):
                if ydata[-1] == 0:
                    ydata.append(0)
                    ydata.append(1)
                else:
                    ydata.append(1)
                    ydata.append(0)
            achannelax.clear()
            achannelax.plot(xdata,ydata)
        for achannelax in self.channel_ax_list.values():
            achannelax.axes.get_xaxis().set_ticks([])
            achannelax.get_yaxis().set_ticks([])
            achannelax.set_ylim(0,1.5)
            achannelax.set_xlim(0,lastend)
        achannelax.get_xaxis().set_ticks(np.arange(0,lastend,1000))
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