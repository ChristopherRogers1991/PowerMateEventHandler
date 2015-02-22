PowerMateEventHandler
==========

# Purpose

PowerMateEventHandler is used to find and read and write to and from a Griffin Power Mate knob.
It allows for collecting raw evdev events, as well as 'ConsolodatedEvents.' Consolodated events
take sets of raw evetns, and convert them into a single event such as a SINGLE_CLICK, DOUBLE_CLICK,
or LONG_CLICK.

One goal of the project was to provide lots of options, but have sensible default values. Each function
should be documented thoroughly, so check the documentation to find out what features
can be customized.

The project started as a way to control my Phillips Hue lights via my RaspberyPi and the PowerMate,
but PowerMateEventHandler seems as if it could have purpose beyond hue lights, so it's been split
off.

# Basic Usage
```
>>> import PowerMateEventHandler as pmeh
>>> p = pmeh.PowerMateEventHandler()
>>> p.set_led_brightness(0)
>>> while True:
...     next = p.get_next(block=False, timeout=1)
...     if next != None:
...         print nextConsolidatedEventCode.LEFT_TURN
...
ConsolidatedEventCode.SINGLE_CLICK
ConsolidatedEventCode.RIGHT_TURN
ConsolidatedEventCode.RIGHT_TURN
ConsolidatedEventCode.RIGHT_TURN
ConsolidatedEventCode.DOUBLE_CLICK
ConsolidatedEventCode.LEFT_TURN
ConsolidatedEventCode.LEFT_TURN
ConsolidatedEventCode.LEFT_TURN
ConsolidatedEventCode.LONG_CLICK
```


# Questions, Comments, Concerns

Email me: ChristopherRogers1991@gmail.com
