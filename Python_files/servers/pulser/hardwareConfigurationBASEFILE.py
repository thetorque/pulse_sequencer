#### THIS IS AN EXAMPLE FILE ####
#### WHEN STARTING A NEW PROJECT, RENAME THE FILE ####
#### AND DO NOT COMMIT YOUR PERSONAL FILE ####

class channelConfiguration(object):
    """
    Stores complete configuration for each of the channels
    """
    def __init__(self, channelNumber, ismanual, manualstate,  manualinversion, autoinversion):
        self.channelnumber = channelNumber
        self.ismanual = ismanual
        self.manualstate = manualstate
        self.manualinv = manualinversion
        self.autoinv = autoinversion
        
class ddsConfiguration(object):
    """
    Stores complete configuration of each DDS board
    """
    def __init__(self, address, allowedfreqrange, allowedamplrange, frequency, amplitude, mode, **args):
        self.channelnumber = address
        self.allowedfreqrange = allowedfreqrange
        self.allowedamplrange = allowedamplrange
        self.frequency = frequency
        self.amplitude = amplitude
        self.t1 = 4000
        self.t2 = 4000
        self.time_step = 4
        self.lattice_parameter = [4000,4000,4]
        self.state = True
        self.boardfreqrange = args.get('boardfreqrange', (0.0, 2000.0))
        self.boardramprange = args.get('boardramprange', (0.000113687, 7.4505806))
        self.board_amp_ramp_range = args.get('board_amp_ramp_range', (0.00174623, 22.8896))
        self.boardamplrange = args.get('boardamplrange', (-37.0, 17.0))
        self.boardphaserange = args.get('boardphaserange', (0.0, 360.0))
        self.off_parameters = args.get('off_parameters', (0.0, -37.0))
        self.phase_coherent_model = args.get('phase_coherent_model', True)        
        self.remote = args.get('remote', False)
        self.name = None #will get assigned automatically
        self.mode = mode
        
class remoteChannel(object):
    def __init__(self, ip, server, **args):
        self.ip = ip
        self.server = server
        self.reset = args.get('reset', 'reset_dds')
        self.program = args.get('program', 'program_dds')
        
class hardwareConfiguration(object):
    channelTotal = 32
    timeResolution = '40.0e-9' #seconds
    timeResolvedResolution = 10.0e-9
    maxSwitches = 1022
    resetstepDuration = 3 #duration of advanceDDS and resetDDS TTL pulses in units of timesteps
    collectionTimeRange = (0.010, 5.0) #range for normal pmt counting
    sequenceTimeRange = (0.0, 85.0) #range for duration of pulse sequence    
    isProgrammed = False
    sequenceType = None #none for not programmed, can be 'one' or 'infinite'
    collectionMode = 'Normal' #default PMT mode
    collectionTime = {'Normal':0.100,'Differential':0.100} #default counting rates
    okDeviceID = 'Pulser2'
    #okDeviceFile = 'photon_2015_06_10.bit'
    okDeviceFile = 'photon_2015_7_13.bit'
    lineTriggerLimits = (0, 15000)#values in microseconds 
    secondPMT = False
    DAC = False
    
    #name: (channelNumber, ismanual, manualstate,  manualinversion, autoinversion)
    channelDict = {
                   'ttl_0':channelConfiguration(0, False, False, False, False), ## camera
                   'AdvanceDDS':channelConfiguration(18, False, False, False, False),
                   'ResetDDS':channelConfiguration(19, False, False, False, False),
                   'AO1':channelConfiguration(20, False, False, False, False), ### triggering for analog board
                   'AO2':channelConfiguration(21, False, False, False, False), ### triggering for analog board
                   'B_x_sign':channelConfiguration(21, True, False, False, False), 
                   'B_y_sign':channelConfiguration(22, True, True, False, False),
                   'B_z_sign':channelConfiguration(23, True, True, False, False), 
                   'dummy_clock':channelConfiguration(24, False, False, False, False), ## for plotting the clock purpose only 
                   
                }
    #address, allowedfreqrange, allowedamplrange, frequency, amplitude, mode, **args):
    ddsDict =   {
                'DDS_0':ddsConfiguration(    0,  (0.1,300.0),   (-37.0,17.0),  39.0,   -10.0),
                                }
    remoteChannels = {
                    }