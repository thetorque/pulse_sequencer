from PyQt4 import QtGui
from PyQt4.QtCore import Qt
class LEDindicator(QtGui.QFrame):
    def __init__(self,name):
        super(LEDindicator, self).__init__()
        self.led = QtGui.QWidget()
        self.led.setAutoFillBackground(True)
        self.setFrameStyle(1)
        self.label = QtGui.QLabel(name)
        self.label.setAlignment(Qt.AlignCenter)
        #self.label.setSizePolicy(QtGui.QSizePolicy.Ignored,QtGui.QSizePolicy.Ignored)
        layout = QtGui.QGridLayout()
        layout.addWidget(self.label,0,0,1,1)
        layout.addWidget(self.led,1,0,5,1)
        self.setLayout(layout)
        self.setOff()


    def setOn(self):
        pal = QtGui.QPalette()
        pal.setColor(self.led.backgroundRole(), Qt.green)
        self.led.setPalette(pal)
        self.update()

    def setOff(self):
        pal = QtGui.QPalette()
        pal.setColor(self.led.backgroundRole(), Qt.lightGray)
        self.led.setPalette(pal)
    
    '''def resizeEvent(self,event):
        font = self.label.font()
        h = self.label.height()*0.8
        font.setPixelSize(h)
        self.label.setFont(font)
'''
if __name__== '__main__':
    import sys
    app = QtGui.QApplication( [])
    widget = LEDindicator('Busy')
    widget.show()
    sys.exit(app.exec_())