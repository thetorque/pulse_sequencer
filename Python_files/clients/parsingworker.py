from PyQt4.QtCore import QThread, pyqtSignal, QObject, pyqtSlot, QMutex, QMutexLocker
from twisted.internet.defer import inlineCallbacks, returnValue  
import re
import time
import numpy as np
import array
from decimal import Decimal
import sys

global harwareConfiguration

class ParsingWorker(QObject):
    parsing_done_trigger = pyqtSignal(list,int)
    finished = pyqtSignal(int)
    busy_trigger = pyqtSignal(bool)
    start = pyqtSignal()
    trackingparameterserver = pyqtSignal(bool)
    parsermessages = pyqtSignal(str)
    new_sequence_trigger = pyqtSignal()


    def __init__(self,hwconfigpath,text,reactor,connection,cntx):
        super(ParsingWorker,self).__init__()
        self.text = text
        self.reactor = reactor
        self.connection = connection
        self.sequence = []
        self.defineRegexPatterns()
        self.start.connect(self.run)
        self.connectedsignal =False
        self.tracking = False
        self.trackingparameterserver.emit(self.tracking)
        self.ParameterID = 0
        self.Busy = False
        self.sequencestorage = []
        self.mutex = QMutex()
        sys.path.append(hwconfigpath)
        self.steadystatedict = None
        global hardwareConfiguration
        from hardwareConfiguration import hardwareConfiguration

    def set_parameters(self,paramdict):
        self.parameters = paramdict

    def update_parameters(self,collection,name,value):
        if collection == "Raman" and name=="Parameters":
            Good,self.ParameterID,A,B,C = value
            self.parameters['Raman']['A'] = A
            self.parameters['Raman']['B'] = B
            self.parameters['Raman']['C'] = C
        else:
            self.parameters[collection][name] = value

        if self.tracking:
            self.run()

    def add_text(self,text):
        self.text = text
        
    def parse_text(self):
        self.sequence =  []
        self.steadystatedict = hardwareConfiguration.ddsDict
        #tic = time.clock()
        defs,reducedtext =  self.findAndReplace(self.defpattern,self.text,re.DOTALL)
        if any(["ParameterVault" in d for d in defs]):
            self.tracking = True
            self.trackingparameterserver.emit(self.tracking)
        elif self.tracking == True:
            self.tracking = False
            self.trackingparameterserver.emit(self.tracking) 
        loops,reducedtext = self.findAndReplace(self.looppattern,reducedtext,re.DOTALL)
        steadys,reducedtext = self.findAndReplace(self.steadypattern,reducedtext,re.DOTALL)
        self.parseDefine(defs,loops)
        self.parseLoop(loops)
        self.parseSteadystate(steadys)
        self.parsePulses(reducedtext)
        #toc = time.clock()
        #print 'Parsing time:                  ',toc-tic
        self.parsing_done_trigger.emit(self.sequence,self.ParameterID)
        self.get_binary_repres()
        


    def findAndReplace(self,pattern,string,flags=0):
        listofmatches = re.findall(pattern,string,flags)
        newstring = re.sub(pattern,'',string,re.DOTALL)
        return listofmatches,newstring

    def defineRegexPatterns(self):
        self.channelpattern = r'Channel\s+([aA0-zZ9]+)\s'
        self.pulsepattern   = r'([a-z]*)\s+([+-]?[0-9]+|[+-]?[0-9]+\.[0-9]+|var\s+[aA0-zZ9]+)\s+([aA-zZ]+)'
        self.looppattern    = r'(?s)(?<=)#repeat(.+?)\s+(.+?)(?=)#endrepeat'
        self.defpattern     = r'(?s)(?<=)#def(.+?)(?=)#enddef'
        self.modepattern    = r'in\s+mode\s+([aA-zZ]+)'
        self.steadypattern     = r'(?s)(?<=)#steadystate(.+?)(?=)#endsteadystate'

    def parseDefine(self,listofstrings,loops):
        for defblock in listofstrings:
            for line in defblock.strip().split('\n'):
                if '=' in line:
                    if "ParameterVault" in line.split():
                        line = re.sub(r'from|ParameterVault','',line)
                        param = line.split()[2]
                        line =re.sub(param,str(self.parameters['Raman'][param]),line)
                    exec('self.' + line.strip())
                else:
                    words = line.strip().split()
                    exec('self.'+words[1]+' = 0.0')


    def parseLoop(self,listofstrings):
        for loopparams, lines in listofstrings:
            begin,end,it = loopparams.split(',')
            lines = lines.strip()
            itervar = begin.split('=')[0]
            begin=int(begin.split('=')[1])
            it = int(it.split('+')[1])
            end = int(end.split('<')[1])
            newlines = ''
            for i in np.arange(begin,end,it):
                for aline in lines.split('\n'):
                    for amatch in re.findall(r'(\(.+?\))',aline):
                        if 'var' in amatch:
                            newsubstr = str(eval(amatch.replace('var ','self.')))
                            aline.replace(amatch,newsubstr)
                        elif itervar in amatch:
                            newsubstr = str(eval(amatch.replace(itervar,str(i))))
                            aline = aline.replace(amatch,newsubstr)
                    newlines += aline + '\n'
            self.parsePulses(newlines)

    def parseSteadystate(self,listofstrings):
        from labrad.units import WithUnit
        for block in listofstrings:
            for line in block.strip().split('\n'):
                name,line = self.findAndReplace(self.channelpattern,line)
                mode,line = self.findAndReplace(self.modepattern,line)
                pulseparameters,line = self.findAndReplace(self.pulsepattern,line.strip())
                for desig,value,unit in pulseparameters:
                    if desig == 'do':
                        try:
                            __freq = WithUnit(float(value),unit)
                        except ValueError:
                            __freq = WithUnit(float(value),unit)
                    elif desig == 'with':
                        try:
                            __amp = WithUnit(float(value),unit)
                        except ValueError:
                            __amp = WithUnit(float(value),unit)
                self.steadystatedict[name[0]].frequency = __freq['MHz']
                self.steadystatedict[name[0]].amplitude =__amp['dBm']

    def parsePulses(self,blockoftext):
        if len(blockoftext.strip())==0:
            return
        for line in blockoftext.strip().split('\n'):
            name,line = self.findAndReplace(self.channelpattern,line)
            mode,line = self.findAndReplace(self.modepattern,line)
            pulseparameters,line = self.findAndReplace(self.pulsepattern,line.strip())
            if mode[0] == 'Normal':
                self.makeNormalPulse(name,0,pulseparameters)

    def makeNormalPulse(self,name,mode,parameters):
        from labrad.units import WithUnit
        __freq, __amp, __begin, __dur = [0]*4
        __phase = WithUnit(0,"deg")
        __ramprate = WithUnit(0,'MHz')
        __ampramp = WithUnit(0,'dBm')
        
        
        for desig,value,unit in parameters:
            if   desig == 'do':
                try:
                    __freq = WithUnit(float(value),unit)
                except ValueError:
                    __freq = WithUnit(eval('self.'+value.split()[1].strip()),unit) 
            elif desig == 'at':
                try:
                    __begin = WithUnit(float(value),unit)
                except ValueError:
                    __begin = WithUnit(eval('self.'+value.split()[1].strip()),unit)
            elif desig == 'for':
                try:
                    __dur = WithUnit(float(value),unit)
                except ValueError:
                    __dur = WithUnit(eval('self.'+value.split()[1].strip()),unit)
            elif desig == 'with':
                try:
                    __amp = WithUnit(float(value),unit)
                except ValueError:
                    __amp = WithUnit(eval('self.'+value.split()[1].strip()),unit)
        self.sequence.append((name[0],__begin,__dur,__freq,__amp,__phase,__ramprate,__ampramp,mode))
    
    
    def get_binary_repres(self):
  #      tottic = time.clock()
        seqObject = Sequence(self.steadystatedict)
   #     tic = time.clock()
        seqObject.addDDSStandardPulses(self.sequence)
 #       toc = time.clock()
#        print 'added pulses    ',toc-tic
        tic = time.clock()
        binary,ttl = seqObject.progRepresentation()
        toc = time.clock()
        # print 'got binary     ',toc-tic
        # import binascii
        # for abyte in [binary[i:i+18] for i in range(2, len(binary)-2, 18)]:
            # print '------------------lol'
            # print binascii.hexlify(abyte),len(abyte)
        # toc = time.clock()
        
        self.mutex.lock()
        try:
            self.sequencestorage = [(str(binary),str(ttl),self.ParameterID)]
        except Exception,e:
            print e
        finally:
            self.mutex.unlock()
     #   print 'Binary compilation time:       ',toc-tottic
     #   print 'compiling done'
        self.new_sequence_trigger.emit()

    def get_sequence(self):
        if self.mutex.tryLock(1):
            try:
                if len(self.sequencestorage)<2:
                    currentsequence, currentttl, currentID = self.sequencestorage[0]
                else:
                    currentsequence, currentttl, currentID = self.sequencestorage.pop(0)
                return currentsequence, currentttl, currentID
            except Exception,e:
                print e
                return None,None,None
            finally:
                self.mutex.unlock()
        else:
            print 'locked'
            return None, None, None
        
    @pyqtSlot()
    def reset_sequence_storage(self):
        locker = QMutexLocker(self.mutex)
        self.sequencestorage = []
        
    @pyqtSlot()
    def run(self):
        self.Busy = True
        self.busy_trigger.emit(self.Busy)
        self.parse_text()
        self.parsermessages.emit('Parser: Parsing done')
        self.Busy = False
        self.busy_trigger.emit(self.Busy)            
        
class Sequence():
    """Sequence for programming pulses"""
    def __init__(self,steadystatedict):
        self.channelTotal = hardwareConfiguration.channelTotal
        self.timeResolution = Decimal(hardwareConfiguration.timeResolution)
        self.MAX_SWITCHES = hardwareConfiguration.maxSwitches
        self.resetstepDuration = hardwareConfiguration.resetstepDuration
        self.ddsDict = steadystatedict

        #dictionary in the form time:which channels to switch
        #time is expressed as timestep with the given resolution
        #which channels to switch is a channelTotal-long array with 1 to switch ON, -1 to switch OFF, 0 to do nothing
        self.switchingTimes = {0:np.zeros(self.channelTotal, dtype = np.int8)} 
        self.switches = 1 #keeps track of how many switches are to be performed (same as the number of keys in the switching Times dictionary"
        #dictionary for storing information about dds switches, in the format:
        #timestep: {channel_name: integer representing the state}
        self.ddsSettingList = []
        self.sequenceTimeRange = hardwareConfiguration.sequenceTimeRange
        self.advanceDDS = hardwareConfiguration.channelDict['AdvanceDDS'].channelnumber
        self.resetDDS = hardwareConfiguration.channelDict['ResetDDS'].channelnumber

        
    def addDDS(self, name, start, num, typ):
        timeStep = self.secToStep(start)
        self.ddsSettingList.append((name, timeStep, num, typ))
        
    def _addNewSwitch(self, timeStep, chan, value):
        if self.switchingTimes.has_key(timeStep):
            if self.switchingTimes[timeStep][chan]: raise Exception ('Double switch at time {} for channel {}'.format(timeStep, chan))
            self.switchingTimes[timeStep][chan] = value
        else:
            if self.switches == self.MAX_SWITCHES: raise Exception("Exceeded maximum number of switches {}".format(self.switches))
            self.switchingTimes[timeStep] = np.zeros(self.channelTotal, dtype = np.int8)
            self.switches += 1
            self.switchingTimes[timeStep][chan] = value
    
    def progRepresentation(self, parse = True):
        if parse:
            self.ddsSettings = self.parseDDS()
            self.ttlProgram = self.parseTTL()
            fullbinary = None
            metablockcounter = 0
            for name, pulsebinary in self.ddsSettings.iteritems():
                addresse = self.ddsDict[name].channelnumber
                blocklist = [pulsebinary[i:i+16] for i in range(0, len(pulsebinary), 16)]
                i = 0
                while i < len(blocklist):
                    repeat = 0
                    currentblock = blocklist[i]
                    j = i+1
                    try:
                        while blocklist[j] == currentblock and repeat < 250:
                            repeat += 1
                            j += 1
                    except IndexError ,e:
                    
                        pass
                    i = j
                    if fullbinary is None:
                        fullbinary = bytearray([addresse,repeat]) + currentblock
                    else:
                        fullbinary += bytearray([addresse,repeat]) + currentblock
                    metablockcounter += 1
                fullbinary[-18] = 128 + addresse
        # import binascii
        # for abyte in [fullbinary[i:i+18] for i in range(0, len(fullbinary), 18)]:
            # print '------------------'
            # print binascii.hexlify(abyte),len(abyte)
        fullbinary = bytearray('e000'.decode('hex'))  + fullbinary + bytearray('F000'.decode('hex'))
        #print binascii.hexlify(fullbinary)
            
        return fullbinary, self.ttlProgram
        
    def userAddedDDS(self):
        return bool(len(self.ddsSettingList))
    
    def _getCurrentDDS(self):
        '''
        Returns a dictionary {name:num} with the reprsentation of the current dds state
        '''
        d = dict([(name,self._channel_to_num(channel)) for (name,channel) in self.ddsDict.iteritems()])
        return d
    
    def _getSteadyStateDDS(self):
        d = dict([(name,self._channel_to_num(channel)) for (name,channel) in self.ddsDict.iteritems()])
        return d

    def _channel_to_num(self, channel):
        '''returns the current state of the channel in the num represenation'''
        if channel.state:
            #if on, use current values. else, use off values
            freq,ampl,mode = (channel.frequency, channel.amplitude,channel.mode)
            self._checkRange('amplitude', channel, ampl)
            self._checkRange('frequency', channel, freq)
        else:
            freq,ampl = channel.off_parameters
        num = self.settings_to_num(channel, freq, ampl,mode)
        return num
    
    def parseDDS(self):
        if not self.userAddedDDS(): return None
        state = self._getCurrentDDS()
        pulses_end = {}.fromkeys(state, (0, 'stop')) #time / boolean whether in a middle of a pulse 
        dds_program = {}.fromkeys(state, '')
        lastTime = 0
        #tic = time.clock()
        entries = sorted(self.ddsSettingList, key = lambda t: t[1] ) #sort by starting time
        #toc = time.clock()
        #print "time sorting    ",toc-tic
        possibleError = (0,'')
        while True:
            try:
                name,start,num,typ = entries.pop(0)
            except IndexError:
                if start  == lastTime:
                    #still have unprogrammed entries
                    self.addToProgram(dds_program, state)
                    self._addNewSwitch(lastTime,self.advanceDDS,1)
                    self._addNewSwitch(lastTime + self.resetstepDuration,self.advanceDDS,-1)
                #add termination
                #for name in dds_program.iterkeys():
                #    dds_program[name] +=  '\x00\x00'
                #at the end of the sequence, reset dds
                lastTTL = max(self.switchingTimes.keys())
                self._addNewSwitch(lastTTL ,self.resetDDS, 1 )
                self._addNewSwitch(lastTTL + self.resetstepDuration ,self.resetDDS,-1)
                return dds_program
            end_time, end_typ =  pulses_end[name]
            if start > lastTime:
                #the time has advanced, so need to program the previous state
                if possibleError[0] == lastTime and len(possibleError[1]): raise Exception(possibleError[1]) #if error exists and belongs to that time
                self.addToProgram(dds_program, state)
                if not lastTime == 0:
                    self._addNewSwitch(lastTime,self.advanceDDS,1)
                    self._addNewSwitch(lastTime + self.resetstepDuration,self.advanceDDS,-1)
                lastTime = start
            if start == end_time:
                #overwite only when extending pulse
                if end_typ == 'stop' and typ == 'start':
                    possibleError = (0,'')
                    state[name] = num
                    pulses_end[name] = (start, typ)
                elif end_typ == 'start' and typ == 'stop':
                    possibleError = (0,'')
            elif end_typ == typ:
                possibleError = (start,'Found Overlap Of Two Pules for channel {}'.format(name))
                state[name] = num
                pulses_end[name] = (start, typ)
            else:
                state[name] = num
                pulses_end[name] = (start, typ)

    def addToProgram(self, prog, state):
        for name,num in state.iteritems():
            if not self.ddsDict[name].phase_coherent_model:
                buf = self._intToBuf(num)
            else:  
                buf = self._intToBuf_coherent(num)
            prog[name] += buf
            
            
    def addDDSFreqModPulses(self, values):
        '''
        input in the form of a list [(name, start, duration, frequency, amplitude, phase, freq_deviation, mod_freq,mode)]
        '''
        for value in values:
            mode = value[-1]
            if mode != 1:
                raise Exception('Wrong mode pulse detected')
            try:
                name,start,dur,freq,ampl = value
                phase  = 0.0
            except ValueError:
                name,start,dur,freq,ampl,phase, freq_deviation, mod_freq, mode = value
            try:
                channel = self.ddsDict[name]
            except KeyError:
                raise Exception("Unknown DDS channel {}".format(name))
            start = start['s']
            dur = dur['s']
            freq = freq['MHz']
            ampl = ampl['dBm']
            phase = phase['deg']
            freq_deviation = freq_deviation['MHz']
            mod_freq = mod_freq['MHz']
            self.addDDSPulse([name,start,dur,freq,ampl,phase,freq_deviation,mod_freq,mode])
    
    def addDDSStandardPulses(self, values):
        '''
        input in the form of a list [(name, start, duration, frequency, amplitude, phase, ramp_rate, amp_ramp_rate,mode)]
        '''
        for value in values:
            mode = value[-1]
            if mode != 0:
                raise Exception('Wrong mode pulse detected')
            try:
                name,start,dur,freq,ampl = value
                phase  = 0.0
                ramprate = 0.0
            except ValueError:
                name,start,dur,freq,ampl,phase, ramp_rate, amp_ramp_rate, mode = value
            try:
                channel = self.ddsDict[name]
            except KeyError:
                raise Exception("Unknown DDS channel {}".format(name))
            start = start['s']
            dur = dur['s']
            freq = freq['MHz']
            ampl = ampl['dBm']
            phase = phase['deg']
            ramp_rate = ramp_rate['MHz']
            amp_ramp_rate = amp_ramp_rate['dBm']
            self.addDDSPulse((name,start,dur,freq,ampl,phase,ramp_rate,amp_ramp_rate,mode))
            
    def addDDSPulse(self,values):
        name,start,dur,freq,ampl,phase,ramp_rate_or_freq_deviation,amp_ramp_rate_or_mod_freq,mode = values
        try:
            channel = self.ddsDict[name]
        except KeyError:
            raise Exception("Unknown DDS channel {}".format(name))
            
        freq_off, ampl_off = channel.off_parameters
        
        if freq == 0:
            freq, ampl = freq_off,ampl_off
        else:
            self._checkRange('frequency', channel, freq)
            self._checkRange('amplitude', channel, ampl)
        num = self.settings_to_num(channel, freq, ampl, mode, phase, ramp_rate_or_freq_deviation, amp_ramp_rate_or_mod_freq)
        if not channel.phase_coherent_model:
            num_off = self.settings_to_num(channel, freq_off, ampl_off, mode)
        else:
            #note that keeping the frequency the same when switching off to preserve phase coherence
            num_off = self.settings_to_num(channel, freq, ampl_off, mode,phase, ramp_rate_or_freq_deviation, amp_ramp_rate_or_mod_freq)
            
        #note < sign, because start can not be 0. 
        #this would overwrite the 0 position of the ram, and cause the dds to change before pulse sequence is launched
        if not start <= self.sequenceTimeRange[1]: 
            raise Exception ("DDS start time out of acceptable input range for channel {0} at time {1}".format(name, start))
        if not start + dur <= self.sequenceTimeRange[1]: 
            raise Exception ("DDS start time out of acceptable input range for channel {0} at time {1}".format(name, start + dur))
        if start == 0:
            self.addDDS(name,start,num,'steadystate')
        elif not dur == 0:#0 length pulses are ignored
            self.addDDS(name, start, num, 'start')
            self.addDDS(name, start + dur, num_off, 'stop')
            
            
            

    def settings_to_num(self, channel, freq, ampl, mode, phase = 0.0, ramp_rate_or_freq_deviation = 0.0, amp_ramp_rate_or_mod_freq = 0.0):
            if not channel.phase_coherent_model:
                num = self._valToInt(channel, freq, ampl)
            else:
                num = self._valToInt_coherent(channel, freq, ampl, phase, ramp_rate_or_freq_deviation, amp_ramp_rate_or_mod_freq, mode)
            return num
            
    def _valToInt_coherent(self, channel, freq, ampl,phase = 0, ramp_rate_or_freq_deviation = 0, amp_ramp_rate_or_mod_freq = 0, mode=0): ### add ramp for ramping functionality
        '''
        takes the frequency and amplitude values for the specific channel and returns integer representation of the dds setting
        freq is in MHz
        power is in dbm
        '''
        ans = 0
        ## changed the precision from 32 to 64 to handle super fine frequency tuning
        if mode in [0,2]: #0 = Normal operation mode, 2 = External trigger mode (TBD)
            ramp_rate = ramp_rate_or_freq_deviation
            amp_ramp_rate = amp_ramp_rate_or_mod_freq
            for val, r, m, precision, extrabits in [(freq,channel.boardfreqrange, 1, 64, False), (ampl,channel.boardamplrange, 2 ** 64,  16, True), (phase,channel.boardphaserange, 2**80, 16, False)]:
                minim, maxim = r
                resolution = (maxim - minim) / float(2**precision - 1)
                seq = int((val - minim)/resolution) #sequential representation
                if extrabits:
                    seq = 4*( seq/4)  # Bitshifting 2 right, then 2 left the DAC is only 14 bits, so we mask the two LSB and use them to encode the operating mode.
                    seq += mode
                ans += m*seq
                
            ### add ramp rate 
            minim, maxim = channel.boardramprange
            resolution = (maxim - minim) / float(2**16 - 1)
            if ramp_rate < minim: ### if the ramp rate is smaller than the minim, thenn treat it as no rampp
                seq = 0
            elif ramp_rate > maxim:
                seq = 2**16-1
            else:
                seq = int((ramp_rate-minim)/resolution)  

            
            ans += 2**96*seq 
            
            ### add amp ramp rate
            
            minim, maxim = channel.board_amp_ramp_range
            minim_slope = 1/maxim
            maxim_slope = 1/minim
            resolution = (maxim_slope - minim_slope) / float(2**16 - 1)
            if (amp_ramp_rate < minim):
                seq_amp_ramp = 0
            elif (amp_ramp_rate>maxim):
                seq_amp_ramp = 1
            else:
                slope = 1/amp_ramp_rate
                seq_amp_ramp = int(np.ceil((slope - minim_slope)/resolution))  # return ceiling of the number

                
            ans += 2**112*seq_amp_ramp
        
        
            
        elif mode == 1: # Frequency modulation mode
            centerfrequency = freq
            ampl = ampl
            phase = phase
            modulationfrequency = amp_ramp_rate_or_mod_freq
            frequencyexcursion = ramp_rate_or_freq_deviation
            
            high_ramp_limit = centerfrequency + frequencyexcursion
            low_ramp_limit  = centerfrequency - frequencyexcursion
            ramping_interval = (10*24.)/2000  # hardcoded in fpga code, 120 ns between each frequency step
            freq_change_rate  = 4 * frequencyexcursion * modulationfrequency # frequency change per second required
            freq_step_size = freq_change_rate * ramping_interval
            
            for val, r, m, precision, extrabits in [(low_ramp_limit,channel.boardfreqrange, 1, 32, False), 
                                                    (high_ramp_limit,channel.boardfreqrange, 2 ** 32, 32, False),
                                                    (ampl,channel.boardamplrange, 2 ** 64,  16, True),
                                                    (phase,channel.boardphaserange, 2**80, 16, False),  
                                                    (freq_step_size, channel.boardfreqrange, 2**96,32,False)]:
                minim, maxim = r
                resolution = (maxim - minim) / float(2**precision - 1)
                seq = int((val - minim)/resolution) #sequential representation
                
                if extrabits:
                    seq = seq & int('1'*14 + '00',2) # the DAC is only 14 bits, so we mask the two LSB and use them to encode the operating mode.
                    seq += mode
                ans += m*seq
                
        return ans
    
    def secToStep(self, sec):
        '''converts seconds to time steps'''
        start = '{0:.9f}'.format(sec) #round to nanoseconds
        start = Decimal(start) #convert to decimal 
        step = ( start / self.timeResolution).to_integral_value()
        step = int(step)
        return step

    def _intToBuf_coherent(self, num):
        '''
        takes the integer representing the setting and returns the buffer string for dds programming
        '''
        ans = 0
        mode = num // 2**64 %2
        #phase
        phase_num = (num // 2**80)%(2**16)
        phase = bytearray(2)
        phase[0] = phase_num%256
        phase[1] = (phase_num//256)%256
        
        
        ### amplitude
        ampl_num = (num // 2**64)%(2**16)
        amp = bytearray(2)
        amp[0] = ampl_num%256
        amp[1] = (ampl_num//256)%256
        
        if mode in [0,2]:
            freq_num = (num % 2**64)  # change according to the new DDS which supports 64 bit tuning of the frequency. Used to be #freq_num = (num % 2**32)*2**32
            b = bytearray(8)          # initialize the byte array to sent to the pusler later
            for i in range(8):
                b[i]=(freq_num//(2**(i*8)))%256
            
           
            ### ramp rate. 16 bit tunability from roughly 116 Hz/ms to 7.5 MHz/ms 
            ramp_rate = (num // 2**96)%(2**16)
            ramp = bytearray(2)
            ramp[0] = ramp_rate%256
            ramp[1] = (ramp_rate//256)%256
            
            ##  amplitude ramp rate
            amp_ramp_rate = (num // 2**112)%(2**16)
            #print "amp_ramp is" , amp_ramp_rate
            amp_ramp = bytearray(2)
            amp_ramp[0] = amp_ramp_rate%256
            amp_ramp[1] = (amp_ramp_rate//256)%256
            
            ##a = bytearray.fromhex(u'0000') + amp + bytearray.fromhex(u'0000 0000')
            ans = phase + amp + amp_ramp + ramp + b
        elif mode == 1: #frequency modulation mode
            low_ramp = (num%(2**32))
            low = bytearray(4)
            for i in range(4):
                low[i]=(low_ramp//(2**(i*8)))%256
            
            high_ramp = (num // 2**32) % (2 **32)
            high = bytearray(4)
            for i in range(4):
                high[i]=(high_ramp//(2**(i*8)))%256
            
            freq_step = (num // 2**96)%(2**32)
            freq_s = bytearray(4)
            for i in range(4):
                freq_s[i]=(freq_step//(2**(i*8)))%256
            ans = phase + amp + freq_s + high + low  
        
        return ans
        
    def _checkRange(self, t, channel, val):
        if t == 'amplitude':
            r = channel.allowedamplrange
        elif t == 'frequency':
            r = channel.allowedfreqrange
        if not r[0]<= val <= r[1]: raise Exception ("channel {0} : {1} of {2} is outside the allowed range".format(channel.name, t, val))
    
    def _getChannel(self, name):
        try:
            channel = self.ddsDict[name]
        except KeyError:
            raise Exception("Channel {0} not found".format(name))
        return channel
        
    def parseTTL(self):
        """Returns the representation of the sequence for programming the FPGA"""
        rep = ''
        lastChannels = np.zeros(self.channelTotal)
        powerArray = 2**np.arange(self.channelTotal, dtype = np.uint64)
        for key,newChannels in sorted(self.switchingTimes.iteritems()):
            channels = lastChannels + newChannels #computes the action of switching on the state
            if (channels < 0).any(): raise Exception ('Trying to switch off channel that is not already on')
            channelInt = np.dot(channels,powerArray)
            rep = rep + self.numToHex(key) + self.numToHex(channelInt) #converts the new state to hex and adds it to the sequence
            lastChannels = channels
        rep = rep + 2*self.numToHex(0) #adding termination
        return rep
        
    def numToHex(self, number):
        number = int(number)
        b = bytearray(4)
        b[2] = number%256
        b[3] = (number//256)%256
        b[0] = (number//65536)%256
        b[1] = (number//16777216)%256
        #print np.array([b[0],b[1],b[2],b[3]])
        return b

