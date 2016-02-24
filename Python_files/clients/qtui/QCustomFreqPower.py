import sys
from PyQt4 import QtGui, QtCore
import numpy as np

class customStepBox(QtGui.QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super(customStepBox, self).__init__(*args, **kwargs)
          
    def textFromValue(self, value):
        ## implement value into MHZ with leading zeros ##
        str_show = "%8.6f" % (10**(value-6.0))
#         str_show = "%8.6f" % value
        return str_show
    
    def valueFromText(self, text):
        value = np.log10(float(text))+6.0
        return value
        


class TextChangingButton(QtGui.QPushButton):
    """Button that changes its text to ON or OFF and colors when it's pressed""" 
    def __init__(self, parent = None):
        super(TextChangingButton, self).__init__(parent)
        self.setCheckable(True)
        self.setFont(QtGui.QFont('MS Shell Dlg 2',pointSize=10))
        self.setSizePolicy(QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Minimum)
        #connect signal for appearance changing
        self.toggled.connect(self.setAppearance)
        self.setAppearance(self.isDown())
    
    def setAppearance(self, down):
        if down:
            self.setText('I')
            self.setPalette(QtGui.QPalette(QtCore.Qt.darkGreen))
        else:
            self.setText('O')
            self.setPalette(QtGui.QPalette(QtCore.Qt.black))
    
    def sizeHint(self):
        return QtCore.QSize(37, 26)

class QCustomFreqPower(QtGui.QFrame):
    def __init__(self, title, switchable = True, parent=None):
        QtGui.QWidget.__init__(self, parent)
        self.setFrameStyle(0x0001 | 0x0030)
        self.makeLayout(title, switchable)
    
    def makeLayout(self, title, switchable):
        layout = QtGui.QGridLayout()
        #labels
        title = QtGui.QLabel(title)
        title.setFont(QtGui.QFont('MS Shell Dlg 2',pointSize=16))
        title.setAlignment(QtCore.Qt.AlignCenter)
        freqlabel = QtGui.QLabel('Frequency (MHz)')
        powerlabel = QtGui.QLabel('Power (dBm)')
        steplabel = QtGui.QLabel('Step (MHz)')
#         if switchable:
#             layout.addWidget(title,0, 0, 1, 3)
#         else:
#             layout.addWidget(title,0, 0, 1, 2)
#         layout.addWidget(freqlabel,2, 0, 1, 1)
#         layout.addWidget(steplabel,2,1,1,1)
#         layout.addWidget(powerlabel,2, 2, 1, 1)
        
        if switchable:
            layout.addWidget(title,1, 0, 1, 1)
        else:
            layout.addWidget(title,1, 0, 1, 1)
        layout.addWidget(freqlabel,0, 1, 1, 1)
        layout.addWidget(steplabel,0,2,1,1)
        layout.addWidget(powerlabel,0, 3, 1, 1)        
        
        
        #editable fields
        self.spinFreq = QtGui.QDoubleSpinBox()
        #self.spinFreq = customSpinBox()
        self.spinFreq.setSizePolicy(QtGui.QSizePolicy.Fixed,QtGui.QSizePolicy.Fixed)
        self.spinFreq.setFont(QtGui.QFont('MS Shell Dlg 2',pointSize=16))
        self.spinFreq.setDecimals(9)
        self.spinFreq.setSingleStep(0.00001) ## set single step here
        self.spinFreq.setRange(10.0,250.0)
        self.spinFreq.setKeyboardTracking(False)
        
        #self.stepBox = QtGui.QDoubleSpinBox()
        self.stepBox = customStepBox()
        self.stepBox.setSizePolicy(QtGui.QSizePolicy.Fixed,QtGui.QSizePolicy.Fixed)
        self.stepBox.setFont(QtGui.QFont('MS Shell Dlg 2',pointSize=13))
        self.stepBox.setDecimals(6)
        self.stepBox.setRange(0.0,6.0)
        self.stepBox.setValue(1.0)
        self.stepBox.setKeyboardTracking(False)
        
        self.stepBox.valueChanged.connect(self.stepChanged)
        
        
        ##
        #self.spinFreq.setStyleSheet("background-color:red;")
        #image = QtGui.QImage("chessboard.gif")
#         pix = QtGui.QPixmap("chessboard.gif")
#         palette = QtGui.QPalette()
#         palette.setBrush(self.backgroundRole(), QtGui.QBrush(pix))
#         #self.spinFreq.setFlat(True)
#         self.spinFreq.setAutoFillBackground(True)
#         self.spinFreq.setPalette(palette)
        #palette = QtGui.QPalette()
        #palette.setBrush(QtGui.QPalette.Background, image)
        #self.spinFreq.set
#        self.spinFreq.setStyleSheet("border-image:url(chessboard);")
         #self.setStyleSheet("background-image:url(chessboard.gif);")
        #self.spinFreq.setAutoFillBackground(True)
        #self.spinFreq.setStyleSheet("background-image:url(chessboard.gif);")
        #self.spinFreq.setStyleSheet("background-color:red;")
        #self.setStyleSheet("background-color:red;")
        ##
        
        self.spinPower = QtGui.QDoubleSpinBox()
        self.spinPower.setFont(QtGui.QFont('MS Shell Dlg 2',pointSize=16))
        self.spinPower.setSizePolicy(QtGui.QSizePolicy.Fixed,QtGui.QSizePolicy.Fixed)
        self.spinPower.setDecimals(2)
        self.spinPower.setSingleStep(0.1)
        self.spinPower.setRange(-145.0, 30.0)
        self.spinPower.setKeyboardTracking(False)
        layout.addWidget(self.spinFreq,     1, 1)
        layout.addWidget(self.stepBox,      1, 2)
        layout.addWidget(self.spinPower,    1, 3)
        if switchable:
            self.buttonSwitch = TextChangingButton()
            layout.addWidget(self.buttonSwitch, 1, 4)
        self.setLayout(layout)
        
    def stepChanged(self, value):
        self.spinFreq.setSingleStep((10**(value-6.0)))
        #print value
    
    def setPowerRange(self, powerrange):
        self.spinPower.setRange(*powerrange)
    
    def setFreqRange(self, freqrange):
        self.spinFreq.setRange(*freqrange)
        
    def setPowerNoSignal(self, power):
        self.spinPower.blockSignals(True)
        power = power['dBm']
        self.spinPower.setValue(power)
        self.spinPower.blockSignals(False)
        
    def setFreqNoSignal(self, freq): 
        self.spinFreq.blockSignals(True)
        freq = freq['MHz']
        self.spinFreq.setValue(freq)
        self.spinFreq.blockSignals(False)
    
    def setStateNoSignal(self, state):
        self.buttonSwitch.blockSignals(True)
        self.buttonSwitch.setChecked(state)
        self.buttonSwitch.setAppearance(state)
        self.buttonSwitch.blockSignals(False)

if __name__=="__main__":
    app = QtGui.QApplication(sys.argv)
    icon = QCustomFreqPower('Control')
    icon.show()
    app.exec_()