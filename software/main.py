import machine, time

time.sleep(0.1)
if machine.Pin(4, machine.Pin.IN).value() == 0:
    print("Not starting main application")
else:
    import bsides25