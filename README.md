# BSides 25 badge

## Hardware

ESP32-C3FH4 (4MB flash)

## Device preparation

Install `esptool` and `mpremote`
```
pip install --user esptool mpremote
```

Install [MicroPython](https://micropython.org/download/ESP32_GENERIC_C3).

For BSides 2025: v1.26.1 (2025-09-11)
```
wget https://micropython.org/resources/firmware/ESP32_GENERIC_C3-20250911-v1.26.1.bin
esptool --port <port> erase_flash
esptool --port <port> --baud 921600 write_flash 0 ESP32_GENERIC_C3-20250911-v1.26.1.bin
```

## Copy files to the badge

```
cd badge_software
mpremote <port> fs cp -r . :/
```

If the code is already running on the badge and `mpremote` does not connect, hold `SELECT` button down while pressing `RESET` button.