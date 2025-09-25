# BSides 25 badge

## Hardware

ESP32-C3FH4 (4MB flash) with WiFi and Bluetooth

128x64 px OLED display (SSD1306)

16 WS2812B (Neopixel compatible) LEDs

USB-C for flashing/charging

[Schematics](./hardware/BSides_2025_badge_v1.1_schematics.pdf)

## Software

The code in `software` is written in MicroPython and loaded onto the badge via USB-C connector.

Update the code by uploading via `mpremote` or directly via some IDE like [Thonny](https://thonny.org/).

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
mpremote <port> fs cp -r software/* :/
```

If the code is already running on the badge and `mpremote` does not connect, hold `SELECT` button down while resetting your badge (pressing `RESET` button or toggling ON/OFF switch).