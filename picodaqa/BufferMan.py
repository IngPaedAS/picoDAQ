'''
.. module BufferMan of picoDAQ

.. author: Guenter Quast <guenter.quast@online.de>
'''
#
from __future__ import print_function, division, unicode_literals
from __future__ import absolute_import

# - class BufferMan
import numpy as np, sys, time, threading
from collections import deque

from multiprocessing import Queue, Process, Array
from multiprocessing.sharedctypes import RawValue, RawArray

from .mpBufManCntrl import *
from .mpOsci import * 

  
class BufferMan(object):
  '''
  A simple Buffer Manager

  Calls rawDAWproducer() to receive data from hardware device
  and stores them in the classes buffer space. Data are served
  from buffer to obligatory consumers (i.e. data qcquisition
  is paused until all consumcers are done) and random consumers
  (receive an event copy, data acquisition continues regardless
  of the consumers' progress)
  '''

  def __init__(self, BMdict, DevConf):
    '''Args:  configuration dictionary
              Device Class             
    '''
    self.DevConf = DevConf  
    self.NChannels = DevConf.NChannels # number of channels in use
    self.NSamples = DevConf.NSamples   # number of samples 
    self.TSampling = DevConf.TSampling # sampling interval
    # function collecting data from hardware device
    self.rawDAQproducer = DevConf.acquireData 

    if "NBuffers" in BMdict: 
      self.NBuffers = BMdict["NBuffers"] # number of buffers
    else:
      self.NBuffers= 16
    if "BMmodules" in BMdict: 
      self.BMmodules = BMdict["BMmodules"] # display modules to start
    else:
      self.BMmodules = []
    if "LogFile" in BMdict:
      self.LogFile = BMdict["LogFile"]
    else:
      self.LogFile = None
    self.flog = None    # file not yet open
    if "verbose" in BMdict: 
      self.verbose = BMdict["verbose"]
    else:
      self.verbose=1   # print (detailed) info if >0 
    if "logTime" in BMdict: 
      self.logTime = BMdict["logTime"] # display modules to start
    else:
      self.logTime = 60 # logging information once per 60 sec

  # set up data structure for BufferManager (numpy arrays)
#    self.BMbuf = np.empty([self.NBuffers, self.NChannels, self.NSamples], 
#          dtype=np.float32 )
#    self.timeStamp = np.empty(self.NBuffers)
#
# use shared c-type memory (allows data sharing across sub-processes)
    self.CBMbuf = RawArray('f', 
                  self.NBuffers * self.NChannels * self.NSamples) 
    self.CtimeStamp = RawArray('f', self.NBuffers )
    self.CtrigStamp = RawArray('i', self.NBuffers )
#  ... and map to numpy arrays
    self.BMbuf = np.frombuffer(self.CBMbuf, 'f').reshape(self.NBuffers, 
        self.NChannels, self.NSamples)
    self.timeStamp = np.frombuffer(self.CtimeStamp, 'f')
    self.trigStamp = np.frombuffer(self.CtrigStamp, 'f')

    self.ibufr = RawValue('i', -1) # read index, synchronization with producer 

    self.procs=[] # list of sub-processes started by BufferMan

  # global variables for producer statistics
    self.Ntrig = RawValue('i', 0)    # count number of readings
    self.Ttrig = RawValue('f', 0.)   # time of last event
    self.Tlife = RawValue('f', 0.)   # DAQ lifetime
    self.readrate = RawValue('f', 0) # current rate                
    self.lifefrac = RawValue('f', 0) # current life-time

  # set up variables for status and accounting  
    self.BMT0 = 0.
    self.tPause = 0.  # time when last paused
    self.dTPause = 0. # total time spent in paused state
    self.ACTIVE = RawValue('b', 0) 
    self.RUNNING = RawValue('b', 0)
    self.STOPPED = False

  # queues (collections.deque() for communication with threads
    self.prod_Que = Queue(self.NBuffers) # acquireData <-> manageDataBuffer
    self.request_ques=[] # consumer request to manageDataBuffer
                # 0:  request event pointer, obligatory consumer
                # 1:  request event data, random consumer 
                # 2:  request event data, obligatoray consumer
    self.consumer_ques=[] # data from manageDataBuffer to consumer

  # multiprocessing Queues for data transfer to subprocesses
    self.mpQues = []
    self.BMInfoQue = None

    self.BMlock = threading.Lock() 
    self.logQ = None
    
  def acquireData(self):
    '''
     Procucer Thread
    
       - collects and stores data in buffers
       - provides all acquired data to manageDataBufer 
       - count number of events and calculate life time

       Arg: funtion handling data acquisition from device

     Communicates with consumer via collections.deque()

    '''
#    self.prlog('*==* BufMan:  !!! acquireData starting')
    tlife = 0.

    ni = 0       # temporary variable
    ts = time.time()
  
    ibufw = -1   # buffer index
    while self.ACTIVE.value:
  # sample data from Picoscope handled by instance ps
      ibufw = (ibufw + 1) % self.NBuffers # next write buffer
      while ibufw==self.ibufr.value:  # wait for consumer done with this buffer
        if not self.ACTIVE.value: 
          if self.verbose: self.prlog ('*==* BufMan.acquireData()  ended')
          return
        time.sleep(0.0005)
#
      while not self.RUNNING.value:   # wait for running status 
        if not self.ACTIVE.value: 
          if self.verbose: self.prlog('*==* BufMan.acquireData()  ended')
          return
        time.sleep(0.01)

# data acquisition from hardware
      e = self.rawDAQproducer(self.BMbuf[ibufw])
      if e == None: 
        if self.verbose: self.prlog('*==* BufMan.acquireData()  ended')
        return
      ttrg, tl = e
      tlife += tl
      self.Tlife.value += tl
      ttrg -= self.BMT0
      self.timeStamp[ibufw] = ttrg  # store time when data became ready
      self.Ttrig.value = ttrg
      self.Ntrig.value += 1
      self.trigStamp[ibufw]=self.Ntrig.value
      self.prod_Que.put( ibufw )
       
# wait for free buffer       
      while self.prod_Que.qsize() == self.NBuffers:
        if not self.ACTIVE.value: 
          if self.verbose: self.prlog('*==* BufMan.acquireData()  ended')
          return
        time.sleep(0.0005)
      
# calculate life time and read rate
      if (self.Ntrig.value - ni) == 10:
        dt = time.time()-ts
        ts += dt
        self.readrate.value = (self.Ntrig.value-ni)/dt
        self.lifefrac.value = (tlife/dt)*100.      
        tlife = 0.
        ni = self.Ntrig.value
    # --- end while  
    if self.verbose: self.prlog('*==* BufMan.acquireData()  ended')
    return
# -- end def acquireData


  def manageDataBuffer(self):
    '''main Consumer Thread 

       - receive data from procuder (acquireData):
       - provide all events for analysis to "obligatory" consumers
       - provide subset of events to "random" consumers (picoVMeter, oscilloscope)

    '''
    t0=time.time()
    n0=0
    n=0
    while self.ACTIVE.value:
      while self.prod_Que.empty(): # wait for data in producer queue
        if not self.ACTIVE.value:
          if self.verbose: self.prlog('*==* BufMan ended')
          return
        time.sleep(0.0005)
      self.ibufr.value = self.prod_Que.get()
      evNr = self.trigStamp[self.ibufr.value]
      evTime=self.timeStamp[self.ibufr.value]

# !debug    self.prlog('ibufr=', self.ibufr.value,'request_ques',self.request_ques)

# check if other threads want data
      l_obligatory=[]
      if len(self.request_ques):
        for i, q in enumerate(self.request_ques):
          if len(q):
            req = q.popleft()
            if req==0:                          # return poiner to Buffer      
              self.consumer_ques[i].append( self.ibufr.value ) 
              l_obligatory.append(i)
            elif req==1:                               # return a copy of data
              self.consumer_ques[i].append( (evNr, evTime, 
                   np.copy(self.BMbuf[self.ibufr.value]) ) )
            elif req==2:                   # return copy and mark as obligatory
              self.consumer_ques[i].append( (evNr, evTime, 
                    np.copy(BMbuf[self.ibufr.value]) ) )
              l_obligatory.append(i)
            else:
              self.prlog('!=! manageDataBuffer: invalid request mode', req)
              sys.exit(1)
# check if other processes want data
      if len(self.mpQues):
        for Q in self.mpQues:
          if Q.empty(): # put an event in the Queue
            Q.put( (evNr, evTime, np.copy(self.BMbuf[self.ibufr.value]) ) )

# wait until all obligatory consumers are done
      if len(l_obligatory):
        while self.ACTIVE.value:
          done = True
          for i in l_obligatory:
            if not len(self.request_ques[i]): done = False
          if done: break
          if not self.ACTIVE.value: 
            if self.verbose: self.prlog('*==* BufMan ended')
            return
          time.sleep(0.0005)        
#  now signal to producer that all consumers are done with this event
      self.ibufr.value = -1

# print event rate
      n+=1
      if time.time()-t0 >= self.logTime:
        t0 = time.time()
        if self.verbose:
          self.prlog('evt %i:  rate: %.3gHz   life: %.2f%%' %(n,
                      self.readrate.value, self.lifefrac.value) )
        if(evNr != n): 
          self.prlog("!!! manageDataBuffer error: ncnt != Ntrig: %i, %i"%(n,
          evNr) )
#   - end while ACTIVE  
    if self.verbose: self.prlog('*==* BufMan ended')
    return
# -end def manageDataBuffer()

  def BMregister(self):
#    global request_ques, consumer_ques
    ''' 
    register a client to Buffer Manager

    Returns: client index
    '''

    self.BMlock.acquire() # my be called by many threads and needs protection ...  
    self.request_ques.append(deque(maxlen=1))
    self.consumer_ques.append(deque(maxlen=1))
    client_index=len(self.request_ques)-1
    self.BMlock.release()
  
    if self.verbose:
      self.prlog("*==* BMregister: new client id=%i" % client_index)
    return client_index

  def BMregister_mpQ(self):
#   multiprocessing Queue
    ''' 
    register a subprocess to Buffer Manager
    
    data will be transferred via a multiprocess Queue
    
    Returns: client index
             multiprocess Queue
    '''

    self.mpQues.append( Queue(1) )
    cid=len(self.mpQues)-1
  
    if self.verbose:
      self.prlog("*==* BMregister_mpQ: new subprocess client id=%i" % cid)
    return cid, self.mpQues[-1]

  def getEvent(self, client_index, mode=1):
    ''' 
    request event from Buffer Manager
 
      Arguments: 

        client_index client:  index as returned by BMregister()
        mode:   0: event pointer (olbigatory consumer)
                1: copy of event data (random consumer)
                2: copy of event (olbigatory consumer)

      Returns: 

        event data
    '''

    self.request_ques[client_index].append(mode)
    cq=self.consumer_ques[client_index]
    while not len(cq):
      if not self.ACTIVE.value: return
      time.sleep(0.0005)
    #self.prlog('*==* getEvent: received event %i'%evNr)
    if mode !=0: # received copy of the event data
      return cq.popleft()
    else: # received pointer to event buffer
      ibr = cq.popleft()
      evNr = self.trigStamp[ibr]
      evTime = self.timeStamp[ibr]
      evData = self.BMbuf[ibr]
      return evNr, evTime, evData
#
  def start(self):
    if self.verbose > 1: 
      self.prlog('*==* BufferMan  starting acquisition threads')
    self.ACTIVE.value = True 

    thr_acquireData=threading.Thread(target=self.acquireData)
    thr_acquireData.daemon=True
    thr_acquireData.setName('acquireData')
    thr_acquireData.start()
# try as sub-process
#    prc_acquireData=Process(name='acquireData', target=self.acquireData)
#    prc_acquireData.start()

    thr_manageDataBuffer=threading.Thread(target=self.manageDataBuffer)
    thr_manageDataBuffer.daemon=True
    thr_manageDataBuffer.setName('manageDataBuffer')
    thr_manageDataBuffer.start()

  # BufferMan Info and control  always started
    self.logQ = Queue()
    maxBMrate = 450.
    self.BMIinterval = 1000.
    self.procs.append(Process(name='BufManCntrl',
      target = mpBufManCntrl, 
      args=(self.getBMCommandQue(), self.logQ, self.getBMInfoQue(), 
#                  cmdQ             BM_logQue       BM_InfoQue      
            maxBMrate, self.BMIinterval) ) )
#             max_rate   update_interval

  # waveform display 
    if 'mpOsci' in self.BMmodules: 
      OScidx, OSmpQ = self.BMregister_mpQ()
      self.procs.append(Process(name='Osci',
                              target = mpOsci, 
                              args=(OSmpQ, self.DevConf, 50., 'event rate') ) )
#                                                     interval
# start BufferMan background processes   
    for prc in self.procs:
#      prc.deamon = True
      prc.start()
      if self.verbose:
        print('      BufferMan: starting process ', prc.name, ' PID =', prc.pid)

  def run(self):
    if self.RUNNING.value:
      self.prlog('*==* BufferMan already running - do nothing')
      return

    tstart = time.time()
    if self.LogFile:
      datetime=time.strftime('%y%m%d-%H%M',time.gmtime(tstart))
      self.flog = open(self.LogFile + '_' + datetime + '.log', 'w')

    if self.verbose: self.prlog('*==* BufferMan T0')
    self.BMT0 = tstart
    if self.verbose: self.prlog('*==* BufferMan start running')

    self.RUNNING.value = True  

  def pause(self):
    if not self.RUNNING.value: 
      print('*==* BufferMan: Pause command recieved, but not running')
      return
    if self.STOPPED:
      print('*==* BufferMan: Pause from Stopped state not possible')
      return
    if self.verbose: self.prlog('*==* BufferMan  pause')
    self.RUNNING.value = False  
    self.tPause = time.time()
    self.readrate.value = 0.

  def resume(self):
    if self.RUNNING.value:
      print('*==* BufferMan: Resume command recieved, but already running')
      return
    if self.STOPPED:
      print('*==* BufferMan: Resume from Stopped state not possible')
      return

    if self.verbose: self.prlog('*==* BufferMan  resume')
    self.RUNNING.value = True
    self.dTPause += (time.time() - self.tPause)  
    self.tPause = 0.

  def setverbose(self, vlevel):
    self.verbose = vlevel

  def readCommands(self, cmdQ):
  # read commands via multiprocessing Queue
    while self.ACTIVE.value:
      cmd = cmdQ.get()
      if cmd == 'P':
        self.pause()
      elif cmd == 'R':
        self.resume()
      elif cmd == 'S': 
        self.stop()    
      elif cmd == 'E': 
        self.end()    
      time.sleep(0.02)

  def getBMCommandQue(self):
    '''multiprocessing Queue for commands  

       starts a background process to read BMCommandQue

       Returns: multiprocess Queue
    '''

    self.BMCommandQue = Queue(1) 
  # start a background thread for reporting
    thr_BMCommandQ = threading.Thread(target=self.readCommands,
                                   args=(self.BMCommandQue,)  )
    thr_BMCommandQ.daemon = True
    thr_BMCommandQ.setName('BMreadCommand')
    thr_BMCommandQ.start()

    if self.verbose:
      self.prlog("*==* BMCommandQue enabled")
    return self.BMCommandQue

  def getStatus(self):
    ''' Returns:
          tuple: Running status, number of events,
                 time of last event, rate, life fraction and buffer level
    '''
    bL = (self.prod_Que.qsize()*100)/self.NBuffers
    stat = self.RUNNING.value
    if self.tPause != 0. :
      t = self.tPause
    else:
      t = time.time()
    return (stat, t - self.BMT0 - self.dTPause, 
           self.Ntrig.value, self.Ttrig.value, self.Tlife.value, 
           self.readrate.value, self.lifefrac.value, bL) 

  def getBMInfoQue(self):
    '''multiprocessing Queue for status information 

       starts a background process to fill BMInfoQue

       Returns: multiprocess Queue
    '''

    self.BMInfoQue = Queue(1) 
  # start a background thread for reporting
    thr_BMInfoQ = threading.Thread(target=self.reportStatus,
                                   args=(self.BMInfoQue,)  )
    thr_BMInfoQ.daemon = True
    thr_BMInfoQ.setName('BMreportStatus')
    thr_BMInfoQ.start()

    if self.verbose:
      self.prlog("*==* BMInfoQue enabled")
    return self.BMInfoQue

  def reportStatus(self, Q):
    '''report Buffer manager staus to a multiprocessing Queue'''
    while not self.STOPPED:
      if Q is not None and Q.empty(): 
        Q.put( self.getStatus()) 
      time.sleep(self.BMIinterval/2000.) # ! convert from ms to s

  def prlog(self, m):
    ''' send a Message, to screen or to LogQ'''
    t = time.time() - self.BMT0 # add time stamp to message
    s = '%.2f '%(t) + m  
    if self.logQ is None:
      print(s)
    else:
      self.logQ.put(s)
    if self.flog != None:
      print(s, file = self.flog)

  def print_summary(self):
    datetime=time.strftime('%y%m%d-%H%M',time.gmtime(self.BMT0))
    if self.flog == None:
      self.flog = open('BMsummary_' + datetime+'.sum', 'w')
    self.prlog('Run Summary: started ' + datetime)
    self.prlog('  Trun=%.1fs  Ntrig=%i  Tlife=%.1fs\n'\
          %(self.TStop - self.BMT0 - self.dTPause, 
            self.Ntrig.value, self.Tlife.value) )
    self.flog.close()
    self.flog = None

  def stop(self):
    if not self.ACTIVE.value:
      print('*==* BufferMan: Stop command recieved, but not running')
      return

    if self.tPause != 0. :    # stopping from paused state
      self.dTPause += (time.time() - self.tPause)
      self.tPause = 0.
    if self.RUNNING.value: 
      self.pause()
      self.tPause = 0.

    self.TStop = time.time()
    self.STOPPED = True

    time.sleep(1.) # allow all events to propagate 

    if self.verbose: 
      self.prlog('*==* BufferMan endig - reached stopped state')
    self.print_summary()
    if self.verbose: 
      print('\n *==* BufferMan ending, RunSummary written')
      print('  Run Summary: Trun=%.1fs  Ntrig=%i  Tlife=%.1fs\n'\
            %(self.TStop - self.BMT0-self.dTPause, 
              self.Ntrig.value, self.Tlife.value) )

  def end(self):
    if not self.ACTIVE.value:
      print('*==* BufferMan: End command recieved, but not active')
      return

    if self.RUNNING.value: # ending from RUNNING state, stop first
      self.stop()

    self.ACTIVE.value = False 
    time.sleep(0.3)

  # stop all sub-processes
    for prc in self.procs:
      if self.verbose: print('    BufferMan: terminating ' + prc.name)
      prc.terminate()
    time.sleep(0.3)

  def __del__(self):
    self.RUNNING.value = False
    self.ACTIVE.value  = False
# - end class BufferMan
