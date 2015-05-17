# requires python-evdev, python-requests
from __future__ import print_function
from evdev import InputDevice, ecodes, UInput
import select
from enum import Enum
import Queue
import os
import time
import threading
import sys


# Constants
BUTTON_PUSHED = 256
KNOB_TURNED = 7
POSITIVE = 1 # button down, or knob clockwise
NEGATIVE = -1 # button up, or knob counter-clockwise


# TODO make these instance variables, and make accessors and mutators
time_down = 0 # time at which the button was last pressed down
led_brightness = 100
flash_duration = .15


class ConsolidatedEventCode(Enum):
    '''
    SINGLE_CLICK = 0
    DOUBLE_CLICK = SINGLE_CLICK + 1
    LONG_CLICK = DOUBLE_CLICK + 1
    RIGHT_TURN = LONG_CLICK + 1
    LEFT_TURN = RIGHT_TURN + 1
    '''
    SINGLE_CLICK = 0
    DOUBLE_CLICK = SINGLE_CLICK + 1
    LONG_CLICK = DOUBLE_CLICK + 1
    RIGHT_TURN = LONG_CLICK + 1
    LEFT_TURN = RIGHT_TURN + 1


class PowerMateEventHandler:

    def __init__(self, brightness=255, read_delay=None, turn_delay=0, long_press_time=.5, double_click_time=.3, dev_dir='/dev/input/'):
        '''
        Find the PowerMateDevice, and get set up to
        start reading from it and writing to it.

        If the device is not found (can happen if the device is not plugged in, or the user does not have permissions to it) a
        DeviceNotFound Exception will be raised.

        @param brightness: The inital brightness of the led in the base.
        @type  brightness: int

        @param read_delay: Timeout when waiting for the device to be readable.
            Having a time out allows the threads to be joinable without waiting
            for another event. None (default) means to wait indefinitely for the device
            to be readable. This will probably yield the best performance, but means the
            thread will not stop after a call to stop() until a new event is triggered.

            Having this configurable  was intendted to allow the reading of events to
            be stoppable (i.e to keep from blocking the thread indefinitely). It was
            made tunable to allow good performance on fast CPUs, but not hog resources
            on slower machines.

            Setting delay to None will cause the thread to block indefinitely.
        @type  read_delay: double

        @param turn_delay: Time in ms between consolidated turns.
        @type  turn_delay: double

        @param long_press_time: time (in s) the button must be held to register a long press
        @type  long_press_time: double

        @param double_click_time: time (in s) the button must be pressed again after a single press to register as a double
        @type  double_click_time: double

        @param dev_dir: The directory in which to look for the device.
        @type  dev_dir: str

        '''

        dev = find_device(dev_dir)

        if dev is None:
            raise Exception("DeviceNotFound")
        else:
            self.__dev = dev

        self.__raw_queue = Queue.Queue()
        self.__raw_thread = None

        self.__consolidated_queue = Queue.Queue()
        self.__consolidated_thread = None

        self.__uinput = get_uinput(dev)

        self.set_led_brightness(brightness)

        self.__event_capture_running = False
        self.__turn_delay = turn_delay
        self.__read_delay = read_delay

        self.__long_press_time = long_press_time
        self.__double_click_time = double_click_time

        self.__time_of_last_turn = 0


    def __get_time_in_ms(self):
        '''
        @return: The currnt time in ms
        @rtype:  int
        '''

        return int(round(time.time() * 1000))


    def __raw(self):
        '''
        Begin raw capture of events, and add them to
        the raw queue.

        '''

        while True:

            if not self.__event_capture_running:
                return

            try:
                # Check if the device is readable
                r,w,x = select.select([self.__dev], [], [], self.__read_delay)
                if r:
                    event = self.__dev.read_one()
                    if not event == None:
                        self.__raw_queue.put(event)
            except IOError:
                # If the device gets disconnected, wait for it to come back
                while True:
                    time.sleep(.5)
                    self.__dev = find_device()
                    if self.__dev != None:
                        self.__uinput = get_uinput(self.__dev)
                        self.set_led_brightness(self.__led_brightness)
                        break


    def __consolidated(self):
        '''
        Begin consolidating events from the raw queue,
        and placing them on the consolidated queue
        '''

        while True:

            if not self.__event_capture_running:
                return

            # Allows the thread to be joinable (i.e. stoppable) without
            # waiting for another event (without the timeout, get would
            # block until the next event)
            try:
                event = self.__raw_queue.get(timeout=self.__read_delay)
            except Queue.Empty:
                continue


            if event.code == KNOB_TURNED:
                self.__knob_turned(event)
            elif event.code == BUTTON_PUSHED:
                if event.value == POSITIVE: # button pressed
                    self.__button_press(self.__get_time_in_ms())


    def __knob_turned(self, event):
        '''
        Helper function for __consolidated and __button_press.

        Queus a turn event if __turn_delay time has passed
        since self.__time_of_last_turn.

        @param event: The turn event
        @type  event: evdev.InputEvent
        '''
        if event_time_in_ms(event) - self.__turn_delay > self.__time_of_last_turn:
          if event.value > 0:
              self.__consolidated_queue.put(ConsolidatedEventCode.RIGHT_TURN)
          else:
              self.__consolidated_queue.put(ConsolidatedEventCode.LEFT_TURN)
          self.__time_of_last_turn = self.__get_time_in_ms()

    def __button_press(self, time_pressed):
        '''
        Helper function for __consolidated.

        Handle a button press event (i.e. consolidtate raw events into
        a single, double, or long click event)

        @param time_pressed: the time the button was first pressed.
        @type  time_pressed: double

        @todo x.x: remove the parameter, and uses of get_time_in_ms that are
        unnecessary. The time can be retrieved directly from the event.
        '''

        x = self.__long_press_time
        check_time = time_pressed

        try:
            event = self.__raw_queue.get(timeout=x)
        except Queue.Empty:
            event = None
        x = x - ((self.__get_time_in_ms() - check_time) / float(1000))

        while ((event == None) or (event.code != BUTTON_PUSHED)) and (x > 0):
            check_time = self.__get_time_in_ms()
            try:
                event = self.__raw_queue.get(timeout=x)
            except Queue.Empty:
                event = None
            x = x - ((self.__get_time_in_ms() - check_time) / float(1000))

        if x <= 0: # was long
            self.__consolidated_queue.put(ConsolidatedEventCode.LONG_CLICK)
            # pull events until button is release (disallow turns while button is down)
            event = self.__raw_queue.get()
            while event.code != BUTTON_PUSHED:
                event = self.__raw_queue.get()

        else:
            # TODO handle double
            try:
                self.__raw_queue.get() # drop the null event
                event = self.__raw_queue.get(timeout=self.__double_click_time)
            except Queue.Empty:
                event = None

            if event == None: # Single click
                self.__consolidated_queue.put(ConsolidatedEventCode.SINGLE_CLICK)

            elif event.code == BUTTON_PUSHED: # Double click
                self.__consolidated_queue.put(ConsolidatedEventCode.DOUBLE_CLICK)

            else: # turn
                self.__knob_turned(event)

        return


    def set_led_brightness(self, brightness):
        '''
        Sets the led in the base to the specified brightness.
        The valid range is 0-255, where 0 is off. Anything
        less than 0 will be treated as zero, anything greater
        than 255 will be treated as 255.
        '''

        if brightness < 0:
            brightness = 0
        elif brightness > 255:
            brightness = 255

        #r,w,x = select.select([], [self.__dev], [])
        #if w:
        self.__uinput.write(ecodes.EV_MSC, ecodes.MSC_PULSELED, brightness)
        self.__uinput.syn()
        self.__led_brightness = brightness


    def flash_led(self, num_flashes=2, brightness=led_brightness, duration=flash_duration, sleep=.15):
        '''
        Convenience function to flash the led in the base. After the flashes, the brightness
        will be reset to whatever it was when this function was called.

        @param num_flashes: number times to flash
        @type  num_flashes: int

        @param brightness: the brightness of the flashes (range defined by set_led_brightness)
        @type  brightness: int

        @param duration: length of each flash in seconds (decimals accepted)
        @type  duration: double

        @param sleep: time between each flash in seconds (decimals accepted)
        @type  sleep: double

        '''

        reset = self.__led_brightness

        for i in range(num_flashes):
            self.set_led_brightness(brightness)
            time.sleep(duration)
            self.set_led_brightness(0)
            time.sleep(sleep)

        self.__led_brightness = reset


    def start(self, raw_only=False):
        '''
        Begin capturing/queueing events. Once this has been run,
        get_next() can be used to start pulling events off the
        queue.
        '''

        self.__event_capture_running = True

        raw = threading.Thread(target = self.__raw)
        raw.daemon = True
        raw.start()

        cons = None
        if not raw_only:
            cons = threading.Thread(target = self.__consolidated)
            cons.daemon = True
            cons.start()

        self.__raw_thread = raw
        self.__consolidated_thread = cons


    def stop(self):
        '''
        Stop the capture/queuing of events.
        '''

        if self.__event_capture_running:
            self.__event_capture_running = False
            if self.__consolidated_thread != None:
                self.__consolidated_thread.join()
            self.__raw_thread.join()


    def get_next(self, block=True, timeout=None):
        '''
        Pull the next consolidated event off the queue, and return it.

        @param block: block until next is available
        @type  block: bool

        @param timeout: block for this long
        @type  timeout: double

        @note: block and timeout are passed directly to queue.get().
               If block is TRUE, the thread will block for timeout seconds for
               the next event. If timeout is None, it will wait indefinitely.
               If block is False, an event will be grabbed only if one is ready
               immediately.

        @return: If start was run with rawOnly=True, an evdev.events.InputEvent;
                 Otherwise, a ConsolidatedEventCode.
                 In either case, None if there is not an event ready and block
                 is False, or timeout is reached.
        @rtype: evdev.events.InputEvent, ConsolidatedEventCode, or None
        '''

        event = None
        if not self.__event_capture_running:
            raise Exception("CaptureNotStarted")
        try:
            if self.__consolidated_thread != None:
                event = self.__consolidated_queue.get(block, timeout)
            else:
                event = self.__raw_queue.get(block, timeout)
        except Queue.Empty:
            pass

        return event


    def set_turn_delay(self, delay):
        '''
        Set the delay between when consolidated events will be registered.

        In an effort to reduce spam from a failry sensative device, this variable
        was created. If multiple turn events come in, the first will register
        a consolidated event, and those that come in within the delay time will
        be ignored. Once the delay threshold has been reached, another consolidated
        event will be registered.

        @param delay: time in ms between turn events.
        @type  delay: double

        '''

        self.__turn_delay = delay


    def set_read_delay(self, delay):
        '''
        This was intendted to allow the reading of events to be stoppable (i.e
        to keep from blocking the thread indefinitely). It was made tunable to
        allow good performance on fast CPUs, but not hog resources on slower
        machines.

        Setting delay to None will cause the thread to block indefinitely. This
        will probably yield the best performance, but means the thread will not
        stop after a call to stop() until a new event is triggered.

        @param delay: Time in seconds to wait for the device to be readable. 
        @type  delay: double

        '''

        self.__read_delay = delay


    def set_double_click_time(self, time):
        '''
        @param time: (in s) the button must be pressed again after a single press to register as a double
        @type  time: double

        '''
        self.__double_click_time = time


    def set_long_click_time(self, time):
        '''
        @param time: (in s) the button must be held to register a long press
        @type  time: double

        '''
        self.__long_click_time = time


def find_device(dev_dir='/dev/input/'):
    '''
    Finds and returns the device in dev_dir

    If the user does not have permission to access a device in dev_dir, an OSError
    Exception will be raised.

    OSErrors are printed to stderr. These will likely happen if the user
    does not have permission to all devices. If the function retrns None
    with the device plugged in, check the permissions on the device.
    (There's probably a better way to do this - check the devices before
    attempting to open them - but that will have to wait for the moment.)

    @return: An evdev.InputDevice. None if the device is not found.
    @rtype:  evdev.InputDevice or None
    '''
    if os.path.exists("/dev/GriffinPowermate"):
        device = InputDevice("/dev/GriffinPowermate")

    else:
        if dev_dir[-2] != '/':
            dev_dir = dev_dir + '/'
        device = None
        for dev in os.listdir(dev_dir):
            if dev.find("event") == 0:
                try:
                    dev = InputDevice(dev_dir + dev)
                    if dev.name.find('Griffin PowerMate') >= 0:
                        device = dev
                        break
                except OSError:
                    print(str(OSError) + " You do not have permissions to use this device: " + dev_dir + dev + ".", file=sys.stderr) 
    return device


def event_time_in_ms(event):
    '''
    @param event: the event to get the time for
    @type  event: evdev.InputEvent


    @return: The time in ms the event occurred (as an int)
    @rtype:  int

    @note: Does this by converting the event microseconds (event.usec) to
    seconds (multiply by 1000000), adding the event seconds (event.sec),
    converting to ms (multiply by 1000), then casting to an int.
    '''

    return int((event.usec / 1000000.0 + event.sec) * 1000) 


def get_uinput(dev):
    '''
    @param dev: An evdev.InputDevice for the PowerMate (see find_device)
    @type  dev: evdev.InputDevice:

    @return: An evdev.UInput for the device. This can be used to write to the
             device (to change the led brightness).
    @rtype:  evdev.UInput
    '''
    uinput = UInput(name="GriffinPowerMateWriter", events={ecodes.EV_MSC:[ecodes.MSC_PULSELED]})
    uinput.device = dev
    uinput.fd = dev.fd
    return uinput
