#!/usr/bin/python
# -*- coding: utf-8 -*-
# script picoDAQ.py
'''
**picoDAQ** Data Aquisition Example with Picoscpe 

Demonstrate data acquisition with PicoScope usb-oscilloscpe 

  Based on python drivers by Colin O'Flynn and Mark Harfouche,
  https://github.com/colinoflynn/pico-python

  tested with  PS2000a and PS4000

  Functions:
 
  - set up PicoScope channel ranges and trigger
  - PicoScope configuration optionally from json file
  - acquire data (implemented as thread)
  - analyse and plot data:

    - DAQtest()    test speed of data acquisitin
    - VMeter       average Voltages with bar graph display
    - Osci         simple oscilloscope
  
  graphics implemented with matplotlib

  For Demo Mode:
     Connect output of signal gnerator to channel B')
     Connect open cable to Channel A \n')
'''

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import sys, time, json, threading
import numpy as np, matplotlib.pyplot as plt
import matplotlib.animation as anim

from picoscope import ps2000a
ps = ps2000a.PS2000a()  
#from picoscope import ps4000
#ps = ps2000a.PS4000()  


# --------------------------------------------------------------
#              define scope settings here
# --------------------------------------------------------------

print('\n*==* script ' + sys.argv[0] + ' executing')

# check for / read command line arguments
if len(sys.argv)==2:
  jsonfname = sys.argv[1]
  print('     scope configurtion from file ' + jsonfname)
  try:
    with open(jsonfname) as f:
      confdict=json.load(f)
      picoChannels=confdict["picoChannels"]
      ChanRanges=confdict["ChanRanges"]
      Nsamples=confdict["Nsamples"]
      sampleTime=confdict["sampleTime"]
      trgChan=confdict["trgChan"]     
      trgThr=confdict["trgThr"]
      trgTyp=confdict["trgTyp"]
      trgTO=confdict["trgTO"] 
      trgDelay=confdict["trgDelay"]
      trgActive=confdict["trgActive"]
      pretrg=confdict["pretrg"]
      frqSigGen=confdict["frqSigGen"]
      swpSigGen=confdict["swpSigGen"]
      ChanColors=confdict["ChanColors"]
      verbose=confdict["verbose"]
      mode=confdict["mode"]
  except:
    print('     failed to read input file ' + jsonfname)
    exit(1)
else:  
# use these default settings
  picoChannels = ['A', 'B'] # channels
# -- signal height:
  ChanRanges=[30E-3, 0.35]  # voltage range chan. A&B
# note: setChannel uses next largest amplitude

# -- signal timing
  Nsamples = 200  # number of samples to take 
  sampleTime = 10.E-6 # duration of sample
# note: setSamplingInterval uses next smallest sampling interval

# -- trigger configuration
  trgChan = 'B'      # trigger channel,
  trgThr = ChanRanges[1]/2.  #  threshold
  trgTyp = 'Rising'  #  type
  trgTO=1000          #  and time-out
  trgDelay = 0 #
  trgActive = True # no triggering if set to False
  pretrg=0.05 # fraction of samples before trigger

# -- signal generator
  frqSigGen = 100E3
  swpSigGen = 'UpDown'

# -- printout control and colors
  verbose=1  # print (detailed) info if >0 
  ChanColors = ['darkblue', 'darkslategrey', 'darkred', 'darkgreen']  
  mode="notest" # "test" "VMeter"
# -- end if - else config settings

# some more defaults and handy constants
ChanOffsets=[0.0, 0.0]  # voltage offsets (not yet funcional in driver)
NChannels = len(picoChannels)
pkToPkSG = 0.4
waveTypeSG = 'Sine'
offsetVoltageSG = 0.
dwellTimeSG = 2/frqSigGen
stopFreqSG = 9 * frqSigGen

# --------------------------------------------------------------
# config settings are the desired inputs, actual possible settings
# (returned after setting up hardware) may be different and are stored here:
Ranges = [0., 0., 0., 0.]  # actual ranges
TSampling = 0.  # actual sampling interval
nSamples = 0    #    and number of samples to be taken

# --------------------------------------------------------------

def picoIni():
  global TSampling, nSamples, Ranges

  if verbose>1: print(__doc__)
  if verbose>0: print("Opening PicsoScope device ...")
#  ps = ps2000a.PS2000a()  
  if verbose>1:
    print("Found the following picoscope:")
    print(ps.getAllUnitInfo())

# configure oscilloscope
# 1) Time Base
  TSampling, nSamples, maxSamples = \
        ps.setSamplingInterval(sampleTime/Nsamples, sampleTime)
  if verbose>0:
    print("  Sampling interval = %.4g µs (%.g4 µs)" \
                   % (TSampling*1E6, sampleTime/Nsamples*1E6) )
    print("  Number of samples = %d (%d)" % (nSamples, Nsamples))
    #print("Maximum samples = %d" % maxSamples)
# 2) Channel Ranges
    for i, Chan in enumerate(picoChannels):
      Ranges[i] = ps.setChannel(Chan, 'AC', ChanRanges[i],
                      VOffset=ChanOffsets[i], enabled=True, BWLimited=False)
      if verbose>0:
        print("  range channel %s: %.3gV (%.3gV)" % (picoChannels[i],
                                                   Ranges[i], ChanRanges[i]))
# 3) enable trigger
  ps.setSimpleTrigger(trgChan, trgThr, trgTyp,
                      trgDelay, trgTO, enabled=trgActive)    
  if verbose>0:
    print(" Trigger channel %s enabled: %.3gV %s" % (trgChan, trgThr, trgTyp))

# 4) enable Signal Generator 
  if frqSigGen !=0. :
    ps.setSigGenBuiltInSimple(frequency=frqSigGen, pkToPk=pkToPkSG,
       waveType=waveTypeSG, offsetVoltage=offsetVoltageSG,  
       sweepType=swpSigGen, dwellTime=dwellTimeSG, stopFreq=stopFreqSG)
    if verbose>0:
      print(" -> Signal Generator enabled: %.3gHz, +/-%.3g V %s"\
            % (frqSigGen, pkToPkSG, waveTypeSG) )
      print("       sweep type %s, stop %.3gHz, Tdwell %.3gs" %\
            (swpSigGen, stopFreqSG, dwellTimeSG) )
 
  return ps
# -- end def picoIni

def getPicoData(ps):
  global RUNNING, ibufw, ibufr, Ntrig, readrate, lifefrac
#  print ('       !!! getPicoData starting')
  Ntrig = 0 # count number of readings
  ni = 0    # temporary variable
  tlife = 0. # life time
  readrate = 0.1
  lifefrac = 0.

  T=Ns*dT # sampling period

  ts=time.time()
  
  while RUNNING:
  # sample data from Picoscope handled by instance ps
    ibufw = (ibufw + 1) % NBuffers # next write buffer
    ps.runBlock(pretrig=pretrg) #
    # wait for PicoScope to set up (~1ms)
    time.sleep(0.001) # set-up time not to be counted as "life time"
    ti=time.time()
    while not ps.isReady():
      if not RUNNING: return
      time.sleep(0.001)
    # waiting time for occurence of trigger counts as life time
    t=time.time()
    timeStamp[ibufw] = t  # store time when data became ready
    tlife += t - ti       # account life time
  # store raw data in global array 
    for i, C in enumerate(picoChannels):
      ps.getDataRaw(C, Ns, data=rawBuf[ibufw, i])
      ps.rawToV(C, rawBuf[ibufw,i], VBuf[ibufw,i], dtype=np.float32)
# alternative:
      #ps.getDataV(C, Ns, dataV=VBuf[ibufw,i], dtype=np.float32)

    Ntrig+=1
    ibufr = ibufw # new data available, client will set to -1 when done
    
# wait for client acknowlege data received        
    while ibufr >= 0: 
      if not RUNNING: return
      time.sleep(0.0012)

    # calculate and display life time and read rate
    if (Ntrig - ni) == 100:
      dt=time.time()-ts
      readrate = (Ntrig-ni)/dt
      lifefrac = (readrate*T + tlife/dt)*100.      
      ts += dt
      tlife = 0.
      ni=Ntrig
  # --- end while  
  print ('          !!! getPicoData()  ended')
  return 0
# -- end def getPicoData

def DAQtest():
# test readout speed: do nothing, just request data from getPicoData
  global ibufr
  t0=time.time()
  n0=0
  n=0
  while True:
    while ibufr < 0:
      time.sleep(0.001)
    ibufr = -1  # signal data received
# display frame rate
    n+=1
    if n-n0 == 100:
      print('rate: %.3gHz   life: %.2f%%' % (readrate,lifefrac))
      n0=n
# -- end def DAQtest

def VMeter():
# Voltage measurement: average of short set of samples 
  global ibufr

  Wtime=500.    # time in ms between samplings
  Npoints = 120  # number of points for history
  ix=np.linspace(-Npoints+1, 0, Npoints) # history plot
  bwidth=0.5
  ind = bwidth + np.arange(NChannels) # bar position in bargraph for voltages
  Vhist=np.zeros( [NChannels, Npoints] )
  stdVhist=np.zeros( [NChannels, Npoints] )

  t0=time.time()
  print('VMeter starting')
  
  def grVMeterIni():
# set up a figure to plot actual voltage and samplings from Picoscope
    fig=plt.figure(figsize=(5., 8.) )
    fig.subplots_adjust(left=0.15, bottom=0.05, right=0.85, top=0.95,
                    wspace=None, hspace=.25)#

    axes=[]
    # history plot
    axes.append(plt.subplot2grid((7,1),(5,0), rowspan=2) )
    axes.append(axes[0].twinx())
    axes[0].set_ylim(-ChanRanges[0], ChanRanges[0])
    axes[1].set_ylim(-ChanRanges[1], ChanRanges[1])
    axes[0].set_xlabel('History')
    axes[0].set_ylabel('Chan A (V)', color=ChanColors[0])
    axes[1].set_ylabel('Chan B (V)', color=ChanColors[1])
    # barchart
    axes.append(plt.subplot2grid((7,1),(1,0), rowspan=4) )
    axbar1=axes[2]
    axbar1.set_frame_on(False)
    axbar2=axbar1.twinx()
    axbar2.set_frame_on(False)
    axbar1.get_xaxis().set_visible(False)
    axbar1.set_xlim(0., NChannels)
    axbar1.axvline(0, color=ChanColors[0])
    axbar1.axvline(NChannels, color=ChanColors[1])
    axbar1.set_ylim(-ChanRanges[0],ChanRanges[0])
    axbar1.axhline(0., color='k', linestyle='-', lw=2, alpha=0.5)
    axbar2.set_ylim(-ChanRanges[1], ChanRanges[1])
    # Voltage in Text format
    axes.append(plt.subplot2grid((7,1),(0,0)) )
    axtxt=axes[3]
    axtxt.set_frame_on(False)
    axtxt.get_xaxis().set_visible(False)
    axtxt.get_yaxis().set_visible(False)
    axtxt.set_title('Picoscope as Voltmeter', size='xx-large')
    
    return fig, axes, axbar1, axbar2
# -- end def grVMeterIni

  def animVMeterIni():
  # initialize objects to be animated
    global bgraph1, bgraph2, graphs, animtxt
    # a bar graph for the actual voltages
#    bgraph = axes[0].bar(ind, np.zeros(NChannels), bwidth,
#                           align='center', color='grey', alpha=0.5)
    bgraph1, = axbar1.bar(ind[0], 0. , bwidth,
                           align='center', color=ChanColors[0], alpha=0.5) 
    bgraph2, = axbar2.bar(ind[1], 0. , bwidth,
                           align='center', color=ChanColors[1], alpha=0.5) 

    # history graphs
    graphs=()
    for i, C in enumerate(picoChannels):
      g,= axes[i].plot(ix, np.zeros(Npoints), color=ChanColors[i])
      graphs += (g,)
    animtxt = axes[3].text(0.05, 0.05 , ' ',
                transform=axes[3].transAxes,
                size='x-large', color='darkblue')
#    return bgraph + graphs + (animtxt,)
    return (bgraph1,) + (bgraph2,) + graphs + (animtxt,)  

# -- end animVMeterIni()

  def animVMeter(n):
    global ibufr
    k=n%Npoints
    while ibufr < 0:
      time.sleep(0.001)
    t=timeStamp[ibufr]
    txt_t='Time  %.1fs' %(t-t0)            
    txt=[]
    V=np.empty(NChannels)
    stdV=np.empty(NChannels)
    for i, C in enumerate(picoChannels):
      V[i] = VBuf[ibufr, i].mean()
      Vhist[i, k] = V[i]
      stdV[i] = VBuf[ibufr, i].std()
      stdVhist[i, k] = stdV[i]
      # update history graph
      if n>0: # !!! fix to avoid permanent display of first object in blit mode
        graphs[i].set_data(ix,
          np.concatenate((Vhist[i, k+1:], Vhist[i, :k+1]), axis=0) )
      else:
        graphs[i].set_data(ix,np.zeros(Npoints))
      txt.append('Chan. %s:   %.3gV +/-%.2g' % (C, Vhist[i,k], stdVhist[i,k]) )
    # update bar chart
#    for r, v in zip(bgraph, V):
#        r.set_height(v)
    if n>0: # !!! fix to avoid permanent display of first object in blit mode
      bgraph1.set_height(V[0])
      bgraph2.set_height(V[1])
    else:  
      bgraph1.set_height(0.)
      bgraph2.set_height(0.)
    animtxt.set_text(txt_t + '\n' + txt[0] + '\n' + txt[1])
    ibufr = -1  # signal data received, triggers next sample
    return (bgraph1,) + (bgraph2,) + graphs + (animtxt,)

# --  end def VMeter
  if verbose>0: print(' -> initializing Voltmeter graphics')
  fig, axes, axbar1, axbar2 = grVMeterIni()
  nrep=Npoints
  ani=anim.FuncAnimation(fig, animVMeter, nrep, interval=Wtime, blit=True,               init_func=animVMeterIni, fargs=None, repeat=True, save_count=None)
   # save_count=None is a (temporary) workaround to fix memory leak in animate
  plt.show()
                
def Oszi():
  # Oszilloscope: display channel readings in time domain

  def grOsziIni():
# set up a figure to plot samplings from Picoscope
  # needs revision if more than 2 Channels present
    fig=plt.figure(figsize=(8.0, 5.0) )
    axes=[]
# channel A
    axes.append(fig.add_subplot(1,1,1, facecolor='ivory'))
    axes[0].set_ylim(-ChanRanges[0],ChanRanges[0])
    axes[0].grid(True)
    axes[0].set_ylabel("Chan. A     Voltage (V)",
                     size='x-large',color=ChanColors[0])
    axes[0].tick_params(axis='y', colors=ChanColors[0])
# channel B
    if len(picoChannels)>1:
      axes.append(axes[0].twinx())
      axes[1].set_ylim(-ChanRanges[1],ChanRanges[1])
      axes[1].set_ylabel("Chan. B     Voltage (V)",
                     size='x-large',color=ChanColors[1])
      axes[1].tick_params(axis='y', colors=ChanColors[1])

  # time base
    axes[0].set_xlabel("Time (ms)", size='x-large') 

    trgidx=picoChannels.index(trgChan)
    trgax=axes[trgidx]
    trgcol=ChanColors[trgidx]

    axes[0].set_title("Trigger: %s, %.3gV %s" % (trgChan, trgThr, trgTyp),
                color=trgcol,
                fontstyle='italic', fontname='arial', family='monospace',
                horizontalalignment='right')
    axes[0].axhline(0., color='k', linestyle='-.', lw=2, alpha=0.5)
    trgax.axhline(trgThr, color=trgcol, linestyle='--')
    trgax.axvline(0., color=trgcol, linestyle='--')

    return fig, axes
# -- end def grOsziIni

  def animOsziIni():
  # initialize objects to be animated
    global graphs, animtxt
    graphs = ()
    for i, C in enumerate(picoChannels):
      g,= axes[i].plot(samplingTimes, np.zeros(Ns), color=ChanColors[i])
      graphs += (g,)
    animtxt = axes[0].text(0.7, 0.95, ' ', transform=axes[0].transAxes,
                   backgroundcolor='white', alpha=0.5)
    return graphs + (animtxt,)
  
  def animOszi(n):
    global n0, t0, ibufr
    if n==0:
      t0=time.time()
      n0=0

  #  wait for data
    while ibufr < 0:
      time.sleep(0.001)

    if n>1:    # !!! fix to avoid permanent display of first line in blit mode
      for i, C in enumerate(picoChannels):
        graphs[i].set_data(samplingTimes, VBuf[ibufr, i])
    else:
      for i, C in enumerate(picoChannels):
        graphs[i].set_data([],[])

    ibufr = -1  # signal data received to getPicoData()
    
# display rate and life time
    if n-n0 == 100:
      txt='rate: %.3gHz  life: %.0f%%' % (readrate, lifefrac)
      animtxt.set_text(txt)
      n0=n
    return graphs + (animtxt,)

  if verbose>0: print(' -> initializing graphics')
  fig, axes = grOsziIni()
  nrep=10000
  ani=anim.FuncAnimation(fig, animOszi, nrep, interval=0., blit=True,               init_func=animOsziIni, fargs=None, repeat=True, save_count=None)
   # save_count=None is a (temporary) workaround to fix memory leak in animate
  plt.show()
#     
    
if __name__ == "__main__": # - - - - - - - - - - - - - - - - - - - - - -

# initialisation
  print('-> initializing PicoScope')
  scope1 = picoIni()
  dT = TSampling  # sampling time-step
  Ns = nSamples
  # array of sampling times (in ms)
  samplingTimes =\
   1000.*np.linspace(-pretrg*Ns*dT, (1.-pretrg)*Ns*dT,Ns)

  # reserve global space for data
  NBuffers= 2
  rawBuf = np.empty([NBuffers, NChannels, Ns], dtype=np.int16 )
  VBuf = np.empty([NBuffers, NChannels, Ns], dtype=np.float32 )
  timeStamp=np.empty(NBuffers)
  ibufw = 0 # index of write buffer
  ibufr = -1 # index of read buffer, -1 if not filled yet

  if verbose>0:
    print(" -> starting data acquisition thread")   
  RUNNING = True

  thrPico=threading.Thread(target=getPicoData, args=(scope1,))
  thrPico.daemon=True
  thrPico.start()
#
# --- infinite LOOP
  try:
    if mode=='test': # test readout speed
      DAQtest()
    elif mode=='VMeter': # Voltmeter mode
      VMeter()
    else:
      Oszi()

  except KeyboardInterrupt:
# END: code to clean up
    if verbose>0: print(' <ctrl C>  -> cleaning up ')
    RUNNING = False  # stop background data acquisition
    time.sleep(1)    #     and wait for task to finish
    scope1.stop()
    scope1.close()
    if verbose>0: print('                      -> exit ')
    exit(0)
    
