# -*- coding: utf-8 -*-
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import numpy as np, time

# class for PicoScope device
from picoscope import ps2000a
picoDevObj = ps2000a.PS2000a()  
#from picoscope import ps4000
#picoDevObj = ps4000a.PS4000()  

class PSconfig(object):
  '''set PicoScope configuration'''

  def __init__(self, confdict=None):
    if confdict==None: confdict={}

# set configuration parameters
    if "picoChannels" in confdict: 
      self.picoChannels = confdict["picoChannels"]
    else:
      self.picoChannels = ['A', 'B'] # channels
    self.NChannels = len(self.picoChannels)

# -- signal height:
  # note: picoscope.setChannel uses next largest amplitude
    if "ChanRanges" in confdict:
      self.ChanRanges = confdict["ChanRanges"]
    else:
      self.ChanRanges=[30E-3, 0.35]  # voltage range chan. A&B
# -- signal timing
  # note: picoscope.setSamplingInterval uses next larger value for 
    if "Nsamples" in confdict:
      self.Nsamples = confdict["Nsamples"]
    else:
      self.Nsamples = 200  # number of samples to take 
    if "sampleTime" in confdict:
      self.sampleTime = confdict["sampleTime"]
    else:
      self.sampleTime = 10.E-6 # duration of sample

# -- trigger configuration
    if "trgChan" in confdict:
      self.trgChan = confdict["trgChan"]  
    else:
      self.trgChan = 'A'      # trigger channel,
    if "trgThr" in confdict:
      self.trgThr = confdict["trgThr"]
    else:
      self.trgThr = ChanRanges[0]/2.  #  threshold
    if "trgTyp" in confdict:
      self.trgTyp = confdict["trgTyp"]
    else:
      self.trgTyp = 'Rising'  #  type
# -- signal generator
    if "frqSG" in confdict:
      self.frqSG = confdict["frqSG"]
    else:
      self.frqSG = 100E3
#
# get other parameters 
    if "ChanModes" in confdict: 
      self.ChanModes = confdict['ChanModes']
    else:
      self.ChanModes = ['AC' for i in range(self.NChannels)]
    if "ChanOffsets" in confdict: 
      self.ChanOffsets = confdict['ChanOffsets']
    else:
      self.ChanOffsets= [0. for i in range(self.NChannels)]  
       # voltage offsets   !!! not yet functional in driver
    if "trgDelay" in confdict: 
      self.trgDelay=confdict["trgDelay"]
    else:
      self.trgDelay = 0        #
    if "trgActive" in confdict: 
      self.trgActive=confdict["trgActive"]
    else:
      self.trgActive = True   # no triggering if set to False
    if "pretrig" in confdict: 
      self.pretrig=confdict["pretrig"]
    else:
      self.pretrig=0.05      # fraction of samples before trigger
    if "trgTO"  in confdict: 
      self.trgTO=confdict["trgTO"] 
    else:
      self.trgTO=1000             #  and time-out
# configuration of AWG
    if "swpSG" in confdict: 
      self.swpSG=confdict["swpSG"]
    else:
      self.swpSG = 'UpDown'
    if "PkToPkSG" in confdict: 
      self.PkToPkSG = confdict["PkToPkSG"]
    else:
      self.PkToPkSG = 0.4 
    if "waveTypeSG" in confdict: 
      self.waveTypeSG = confdict["waveTypeSG"]
    else:
      self.waveTypeSG = 'Sine'
    if "stopFreqSG" in confdict: 
      self.stopFreqSG = confdict["stopFreqSG"]
    else:
      self.stopFreqSG = 9 * self.frqSG
    if "dwellTimeSG" in confdict: 
      self.dwellTimeSG = confdict["dwellTimeSG"]
    else:
      if self.frqSG != 0:     
        self.dwellTimeSG = 10./self.frqSG
      else:
        self.dwellTimeSG = 0.
    if "offsetVoltageSG" in confdict: 
      self.offsetVoltageSG = confdict["offsetVoltageSG"] 
    else:
      self.offsetVoltageSG = 0.  

# control printout, colors, ...
    if "verbose" in confdict: 
      self.verbose = confdict["verbose"]
    else:
      self.verbose=1   # print (detailed) info if >0 

    if "ChanColors" in confdict: 
      self.ChanColors=confdict["ChanColors"]
    else:
      self.ChanColors = ['darkblue', 'darkslategrey', 'darkred', 'darkgreen']   
    if "mode" in confdict: 
      self.mode = confdict["mode"]
    else:
      self.mode="osci"   # "osci" "demo" "VMeter" "test" 

# configuration parameters only known after initialisation
    self.TSampling = 0.
    self.NSamples = 0.
    self.CRanges = [0., 0., 0., 0.]
   
    self.picoDevObj = picoDevObj

  def setSamplingPars(self, dT, NSamples, CRanges):
    self.TSampling = dT    # sampling interval
    self.NSamples = NSamples # number of samples
    self.CRanges = CRanges # channel ranges

  def setBufferManagerPointer(self, BM):
    self.BM = BM

  def picoIni(self):
    ''' initialise device controlled by class PSconf '''
    verbose = self.verbose

    if verbose>1: print(__doc__)
    if verbose>0: print("Opening PicsoScope device ...")
    if verbose>1:
      print("Found the following picoscope:")
      print(self.picoDevObj.getAllUnitInfo())

# configure oscilloscope
# 1) Time Base
    TSampling, NSamples, maxSamples = \
      self.picoDevObj.setSamplingInterval(\
       self.sampleTime/self.Nsamples, self.sampleTime)
    if verbose>0:
      print("  Sampling interval = %.4g µs (%.4g µs)" \
                   % (TSampling*1E6, self.sampleTime*1E6/self.Nsamples ) )
      print("  Number of samples = %d (%d)" % (NSamples, self.Nsamples))
    #print("Maximum samples = %d" % maxSamples)
# 2) Channel Ranges
      CRanges=[]
      for i, Chan in enumerate(self.picoChannels):
        CRanges.append(picoDevObj.setChannel(Chan, self.ChanModes[i], 
                   self.ChanRanges[i], VOffset=self.ChanOffsets[i], 
                   enabled=True, BWLimited=False) )
        if verbose>0:
          print("  range channel %s: %.3gV (%.3gV)" % (self.picoChannels[i],
                  CRanges[i], self.ChanRanges[i]))
# 3) enable trigger
    picoDevObj.setSimpleTrigger(self.trgChan, self.trgThr, self.trgTyp,
          self.trgDelay, self.trgTO, enabled=self.trgActive)    
    if verbose>0:
      print("  Trigger channel %s enabled: %.3gV %s" % (self.trgChan, 
          self.trgThr, self.trgTyp))

# 4) enable Signal Generator 
    if self.frqSG !=0. :
      picoDevObj.setSigGenBuiltInSimple(frequency=self.frqSG, 
         pkToPk=self.PkToPkSG, waveType=self.waveTypeSG, 
         offsetVoltage=self.offsetVoltageSG, sweepType=self.swpSG, 
         dwellTime=self.dwellTimeSG, stopFreq=self.stopFreqSG)
      if verbose>0:
        print(" -> Signal Generator enabled: %.3gHz, +/-%.3g V %s"\
            % (self.frqSG, self.PkToPkSG, self.waveTypeSG) )
        print("       sweep type %s, stop %.3gHz, Tdwell %.3gs" %\
            (self.swpSG, self.stopFreqSG, self.dwellTimeSG) )

    self.setSamplingPars(TSampling, NSamples, CRanges) # store in config class
    # reserve static buffer for picoscope driver for storing raw data
    self.rawBuf = np.empty([self.NChannels, NSamples], dtype=np.int16 )

# -- end def picoIni

  def acquirePicoData(self, buffer):
    '''
    read data from device
      this part is hardware (i.e. driver) specific code for PicoScope device

      Args:
        buffer: space to store data

      Returns:
        ttrg: time when device became ready
        tlife life time of device
  '''
    picoDevObj.runBlock(pretrig=self.pretrig) #
    # wait for PicoScope to set up (~1ms)
    time.sleep(0.001) # set-up time not to be counted as "life time"
    ti=time.time()
    while not picoDevObj.isReady():
      if not self.BM.RUNNING: return -1, -1
      time.sleep(0.001)
    # waiting time for occurence of trigger is counted as life time
    ttrg=time.time()
    tlife = ttrg - ti       # account life time
  # store raw data in global array 
    for i, C in enumerate(self.picoChannels):
      picoDevObj.getDataRaw(C, self.NSamples, data=self.rawBuf[i])
      picoDevObj.rawToV(C, self.rawBuf[i], buffer[i], dtype=np.float32)
# alternative:
     # picoDevObj.getDataV(C, NSamples, dataV=VBuf[ibufw,i], dtype=np.float32)
    return ttrg, tlife
# - end def acquirePicoData()