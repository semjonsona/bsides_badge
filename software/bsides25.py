import sys
import os
import ubinascii
import urandom
import network
import socket
import ssl
import json
import uasyncio as asyncio
import time, micropython
from machine import Pin, I2C
import ssd1306, neopixel
import math

# Writer
from writer.writer import Writer
import writer.freesans20 as freesans20
import writer.font10 as font10
import writer.font6 as font6

# -----------------------
# Settings
# -----------------------
I2C_SCL = 1
I2C_SDA = 0
OLED_WIDTH = 128
OLED_HEIGHT = 64

NEOPIXEL_PIN = 3
NEOPIXEL_COUNT = 16
NEOPIXEL_FPS = 50

# Buttons
BTN_NEXT_PIN = 5      # Next / Increase
BTN_PREV_PIN = 8      # Previous / Decrease
BTN_SELECT_PIN = 4    # Enter
BTN_BACK_PIN = 9      # Back
DEBOUNCE_MS = 50

# Auto-repeat
REPEAT_DELAY = 500     # ms before auto-repeat starts
REPEAT_INTERVAL = 10  # ms between repeats

INACTIVITY_TIMEOUT = 5000  # ms

# -----------------------
# Globals
# -----------------------
button_event = None
last_button = None
last_activity = 0

BTN_NEXT = 1
BTN_PREV = 2
BTN_SELECT = 3
BTN_BACK = 4

btn_state = {}       # {btn_id: pressed or not}
repeat_tasks = {}    # {btn_id: task}
_last_event_ms = {}  # debounce tracking

i2c_oled = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))
oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c_oled)
wri6  = Writer(oled, font6, verbose=False)
wri10 = Writer(oled, font10, verbose=False)
wri20 = Writer(oled, freesans20, verbose=False)

username_wri = wri20
username_lines = None

# -----------------------
# Parameters
# -----------------------

class Parameter:
    def __init__(self, name, value, maxval):
        self.name = name
        self.value = value
        self.maxval = maxval

# -----------------------
# LED effects
# -----------------------

led_startup    = True
led_effects    = []
led_effect     = Parameter("Light_effect", 0, 3)
led_brightness = Parameter("Brightness", 10, 100)
led_hue        = Parameter("Hue", 180, 360)
led_sat        = Parameter("Saturation", 100, 100)
led_speed      = Parameter("Speed", 30, 100)

# -----------------------
# JSON parameter storage
# -----------------------

params = {
    "Brightness": led_brightness,
    "Hue": led_hue,
    "Saturation": led_sat,
    "Speed": led_speed,
    "Light_effect" : led_effect
}

# --- Snake high score param (persistent in params.json) ---
snake_high_score = Parameter("SnakeHighScore", 0, 9999)
params["SnakeHighScore"] = snake_high_score

FILENAME = "params.json"

def save_params():
    data = {name: param.value for name, param in params.items()}
    with open(FILENAME, "w") as f:
        json.dump(data, f)

def load_params():
    try:
        with open(FILENAME, "r") as f:
            data = json.load(f)
            for name, val in data.items():
                if name in params:
                    params[name].value = val
    except OSError:
        # file not found, keep defaults
        pass

# -----------------------
# Username and ID
# -----------------------
USERNAME = "Semjon/Sona Kravtsenko"

# -----------------------
# Hardware init
# -----------------------

def init_neopixels():
    np = neopixel.NeoPixel(Pin(NEOPIXEL_PIN, Pin.OUT), NEOPIXEL_COUNT)
    np.fill((0,0,0))
    np.write()
    return np

# -----------------------
# Button IRQ handling
# -----------------------
def _push_button(btn_id):
    global last_button, last_activity
    last_button = btn_id
    last_activity = time.ticks_ms()
    if button_event:
        button_event.set()

def _schedule_push(btn):
    btn_id, pin_state = btn
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_event_ms.get(btn_id, 0)) < DEBOUNCE_MS:
        return
    _last_event_ms[btn_id] = now

    if pin_state == 0:  # pressed
        btn_state[btn_id] = 1
        _push_button(btn_id)
        # start repeat task for Next/Prev
        if btn_id in (BTN_NEXT, BTN_PREV):
            repeat_tasks[btn_id] = asyncio.create_task(_repeat_task(btn_id))
    else:  # released
        btn_state[btn_id] = 0
        t = repeat_tasks.pop(btn_id, None)
        if t:
            t.cancel()

def make_irq(btn_id):
    def handler(pin):
        micropython.schedule(_schedule_push, (btn_id, pin.value()))
    return handler

def setup_buttons():
    cfg = [(BTN_NEXT_PIN, BTN_NEXT),
           (BTN_PREV_PIN, BTN_PREV),
           (BTN_SELECT_PIN, BTN_SELECT),
           (BTN_BACK_PIN, BTN_BACK)]
    for pin_num, btn_id in cfg:
        p = Pin(pin_num, Pin.IN)  # external pull-ups
        p.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING, handler=make_irq(btn_id))

async def _repeat_task(btn_id):
    try:
        await asyncio.sleep_ms(REPEAT_DELAY)
        while btn_state[btn_id]:
            _push_button(btn_id)
            await asyncio.sleep_ms(REPEAT_INTERVAL)
    except asyncio.CancelledError:
        return

# -----------------------
# Screen base class
# -----------------------
class Screen:
    def __init__(self, oled):
        self.oled = oled

    def render(self):
        pass

    async def handle_button(self, btn):
        pass

# -----------------------
# Lights screens
# -----------------------
class ParamScreen(Screen):
    def __init__(self, oled, writer, param, returnscreen, barfill=False, wraparound=False):
        super().__init__(oled)
        self.writer = writer
        self.param = param
        self.returnscreen = returnscreen
        self.barfill = barfill
        self.wraparound = wraparound

    def render(self):
        self.oled.fill(0)

        val = self.param.value
        bar_x = 0
        bar_y = 30
        bar_w = self.oled.width
        bar_h = 10
        self.oled.rect(bar_x, bar_y, bar_w, bar_h, 1)

        # Knob/fill position
        pos = bar_x + (val * (bar_w - 1)) // self.param.maxval
        if not self.barfill:
            self.oled.vline(pos, bar_y, bar_h, 1)
        else:
            self.oled.fill_rect(bar_x, bar_y, pos, bar_h, 1)

        # Numeric display
        self.writer.set_textpos(self.oled, 50, 0)
        self.writer.printstring("{}: {:3d}".format(self.param.name, val))
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT and (self.wraparound or self.param.value < self.param.maxval):
            self.param.value = (self.param.value + 1) % (self.param.maxval + 1)
        elif btn == BTN_PREV and (self.wraparound or self.param.value > 0):
            self.param.value = (self.param.value - 1) % (self.param.maxval + 1)
        elif btn in (BTN_SELECT, BTN_BACK):
            return self.returnscreen(self.oled)
        return self

class BrightnessScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_brightness, LightsScreen, barfill=True, wraparound=False)

class SpeedScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_speed, LightsScreen, barfill=True, wraparound=False)

class SaturationScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_sat, LightsScreen, barfill=False, wraparound=False)

class HueScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_hue, LightsScreen, barfill=False, wraparound=True)

class ListScreen(Screen):
    def __init__(self, oled, title, items):
        super().__init__(oled)
        self.title = title
        self.items = items  # list of strings or tuples
        self.headerwriter = wri10
        self.listwriter = wri6
        self.index = 0
        self.offset = 0  # first visible item

        # metrics
        self.line_height = self.listwriter.font.height()
        self.rows = (self.oled.height - 20) // self.line_height  # room below header

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.index = (self.index + 1) % len(self.items)
        elif btn == BTN_PREV:
            self.index = (self.index - 1) % len(self.items)
        elif btn == BTN_BACK:
            return self.on_back()
        elif btn == BTN_SELECT:
            return self.on_select(self.index)

        # adjust scroll offset
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + self.rows:
            self.offset = self.index - self.rows + 1

        return self

    def render(self):
        self.oled.fill(0)
        self.headerwriter.set_textpos(self.oled, 0, 0)
        self.headerwriter.printstring(self.title)

        visible = range(self.offset, min(len(self.items), self.offset + self.rows))
        for row, i in enumerate(visible):
            y = 20 + row * self.line_height
            prefix = ">" if i == self.index else " "
            self.listwriter.set_textpos(self.oled, y, 0)
            self.listwriter.printstring("{}{}".format(prefix, self.items[i][0]))

        self.oled.show()

    # --- to be customized in child classes ---
    def on_select(self, index):
        pass

    def on_back(self):
        pass

class EffectScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "LED effects", led_effects)

    def on_select(self, index):
        global led_effect
        led_effect.value = index
        return self

    def on_back(self):
        return LightsScreen(self.oled)

lights_screens = [("Effects", EffectScreen),
                  ("Brightness", BrightnessScreen),
                  ("Hue", HueScreen),
                  ("Saturation", SaturationScreen),
                  ("Speed", SpeedScreen)]

class LightsScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "Lights", lights_screens)

    def on_select(self, index):
        cls = lights_screens[index][1]
        return cls(self.oled)

    def on_back(self):
        save_params()
        return MenuScreen(self.oled)


# -----------------------
# Utils screens
# -----------------------

class StopwatchScreen(Screen):
    """
    Simple stopwatch with live updating.
    Controls:
      SELECT: Start/Stop
      PREV:   Reset (when stopped)
      BACK:   Exit
    """
    def __init__(self, oled):
        super().__init__(oled)
        self.running = False
        self.start_ms = 0
        self.elapsed_ms = 0
        # start a small updater so time refreshes while running
        self._ticker = asyncio.create_task(self._tick())

    async def _tick(self):
        try:
            while True:
                if screen is self and self.running:
                    self.render()
                await asyncio.sleep_ms(100)
        except asyncio.CancelledError:
            return

    def _fmt(self, ms):
        s, cs = divmod(ms // 10, 100)      # centiseconds
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return "%02d:%02d:%02d.%02d" % (h, m, s, cs)

    def render(self):
        # update elapsed if running
        if self.running:
            now = time.ticks_ms()
            self.elapsed_ms = time.ticks_add(
                time.ticks_diff(now, self.start_ms), 0
            ) + self._paused_base

        self.oled.fill(0)
        # Title
        wri10.set_textpos(self.oled, 0, 0)
        wri10.printstring("Stopwatch")
        # Time (big)
        wri20.set_textpos(self.oled, 28, 0)
        wri20.printstring(self._fmt(self.elapsed_ms))
        # Hints
        wri6.set_textpos(self.oled, 50, 0)
        if self.running:
            wri6.printstring("SELECT=Stop  BACK=Exit")
        else:
            wri6.printstring("SELECT=Start PREV=Reset BACK=Exit")
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_SELECT:
            if not self.running:
                # starting: remember base elapsed (supports resume)
                self._paused_base = self.elapsed_ms
                self.start_ms = time.ticks_ms()
                self.running = True
            else:
                # stopping: lock in elapsed
                now = time.ticks_ms()
                self.elapsed_ms = self._paused_base + time.ticks_diff(now, self.start_ms)
                self.running = False
        elif btn == BTN_PREV and not self.running:
            self.elapsed_ms = 0
            self._paused_base = 0
        elif btn == BTN_BACK:
            # stop updater task when leaving
            self._ticker.cancel()
            return UtilsScreen(self.oled)
        self.render()
        return self

    # initialize paused base
    _paused_base = 0


utils_screens = [("Stopwatch", StopwatchScreen)]

class UtilsScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "Utils", utils_screens)

    def on_select(self, index):
        cls = utils_screens[index][1]
        return cls(self.oled)

    def on_back(self):
        return MenuScreen(self.oled)



class GalleryScreen(Screen):
    def __init__(self, oled):
        super().__init__(oled)
        self.index = 0
        import gallery
        self.fbs = gallery.fbs
        self.colors = gallery.colors

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.index = (self.index + 1) % len(self.fbs)
        elif btn == BTN_PREV:
            self.index = (self.index - 1) % len(self.fbs)
        elif btn == BTN_BACK:
            return self.on_back()
        elif btn == BTN_SELECT:
            return self.on_select(self.index)
        return self

    def render(self):
        self.oled.fill(0)
        self.oled.blit(self.fbs[self.index], 0, 0)
        self.oled.show()

    def on_select(self, index):
        pass

    def on_back(self):
        return MenuScreen(self.oled)


# -----------------------
# Text screens
# -----------------------

class TextScreen(Screen):
    def __init__(self, oled, writer, text):
        super().__init__(oled)
        self.wri = writer

        # wrap long text
        self.text = self._wrap_text(text)

        # metrics
        self.line_height = self.wri.font.height()
        self.rows = oled.height // self.line_height
        self.offset = 0

    def _wrap_text(self, text):
        lines = []
        # split paragraphs by explicit newline
        for para in text.split("\n"):
            words = para.split()
            line = ""
            for word in words:
                test_line = (line + " " + word).strip()
                if self.wri.stringlen(test_line) <= self.oled.width:
                    line = test_line
                else:
                    lines.append(line)
                    line = word
            if line:
                lines.append(line)
            if para == "":  # preserve blank lines
                lines.append("")
        return lines

    def render(self):
        self.oled.fill(0)
        y = 0
        for i in range(self.offset, min(len(self.text), self.offset + self.rows)):
            self.wri.set_textpos(self.oled, y, 0)
            self.wri.printstring(self.text[i])
            y += self.line_height
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT and self.offset + self.rows < len(self.text):
            self.offset += 1
        elif btn == BTN_PREV and self.offset > 0:
            self.offset -= 1
        elif btn == BTN_BACK:
            return MenuScreen(self.oled)
        return self

class AboutScreen(TextScreen):
    def __init__(self, oled):
        text = (
            "BSides Tallinn 2025 badge, mod by Sona"
        )
        super().__init__(oled, wri6, text)

class SnakeScreen(Screen):
    """
    Snake for 128x64 SSD1306.
    - Grid: 4x4 px cells
    - HUD row at top with boundary line; full border around playfield.
    - Controls:
        NEXT  -> turn right
        PREV  -> turn left
        SELECT-> pause/resume (or restart on game over)
        BACK  -> exit to menu

    NOTE: In ui_task(), do not auto-render when current screen is SnakeScreen.
    """
    CELL = 4
    DIRS = [(1,0), (0,1), (-1,0), (0,-1)]  # R, D, L, U

    def __init__(self, oled):
        super().__init__(oled)

        # ----- GEOMETRY -----
        self.HUD_H = wri6.font.height()                 # your build reports 14
        self.GRID_W = OLED_WIDTH // self.CELL           # 32
        self.GRID_H = (OLED_HEIGHT - self.HUD_H) // self.CELL  # e.g. 12
        self.GRID_Y0 = self.HUD_H                       # playfield starts below HUD

        # Playfield pixel bounds
        self.x_left   = 0
        self.x_right  = self.oled.width - 1            # 127
        self.y_top    = self.GRID_Y0
        self.y_bot    = self.GRID_Y0 + self.GRID_H * self.CELL - 1  # e.g. 61

        # ----- GAME STATE -----
        self.running = True
        self.paused = False
        self.tick_ms_base = 180
        self.tick_ms_min  = 70
        self.tick_ms = self.tick_ms_base
        self.score = 0

        try:
            self.high_score = snake_high_score.value
        except NameError:
            self.high_score = 0

        self.dir_idx = 0  # right
        cx = self.GRID_W // 2
        cy = self.GRID_H // 2
        self.snake = [(cx, cy), (cx-1, cy), (cx-2, cy), (cx-3, cy)]
        self.food = self._rand_empty_cell()
        self.game_over = False

        # Start loop last
        self._task = asyncio.create_task(self._loop())
        self.render()

    # ---------- helpers ----------
    def _cell_free(self, x, y):
        return (x, y) not in self.snake

    def _rand_empty_cell(self):
        for _ in range(200):
            x = urandom.getrandbits(5) % self.GRID_W     # 0..31
            y = urandom.getrandbits(5) % self.GRID_H     # 0..GRID_H-1
            if self._cell_free(x, y):
                return (x, y)
        for yy in range(self.GRID_H):
            for xx in range(self.GRID_W):
                if self._cell_free(xx, yy):
                    return (xx, yy)
        return (0, 0)

    def _turn_left(self):
        self.dir_idx = (self.dir_idx - 1) % 4

    def _turn_right(self):
        self.dir_idx = (self.dir_idx + 1) % 4

    def _advance(self):
        dx, dy = self.DIRS[self.dir_idx]
        hx, hy = self.snake[0]
        nx, ny = hx + dx, hy + dy

        # grid-bounds collision
        if nx < 0 or nx >= self.GRID_W or ny < 0 or ny >= self.GRID_H:
            self._end_game()
            return

        # self collision
        if (nx, ny) in self.snake:
            self._end_game()
            return

        # move
        self.snake.insert(0, (nx, ny))

        # eat
        if (nx, ny) == self.food:
            self.score += 1
            self.tick_ms = max(self.tick_ms_min, self.tick_ms_base - self.score * 6)
            self.food = self._rand_empty_cell()
        else:
            self.snake.pop()

    def _end_game(self):
        self.game_over = True
        if self.score > self.high_score:
            self.high_score = self.score
            try:
                snake_high_score.value = self.high_score
                save_params()
            except Exception:
                pass
        # show overlay immediately
        self.render()

    async def _loop(self):
        try:
            while self.running:
                if not self.paused and not self.game_over:
                    self._advance()
                    self.render()
                await asyncio.sleep_ms(self.tick_ms)
        except asyncio.CancelledError:
            return

    # ---------- drawing ----------
    def _draw_hud(self):
        # Clear HUD band
        self.oled.fill_rect(0, 0, self.oled.width, self.HUD_H, 0)

        # Left: score
        wri6.set_textpos(self.oled, 0, 0)
        wri6.printstring("SCORE:{:d}".format(self.score))

        # Right: high score
        hi_txt = "HI:{:d}".format(self.high_score)
        x_hi = self.oled.width - wri6.stringlen(hi_txt)
        wri6.set_textpos(self.oled, 0, x_hi)
        wri6.printstring(hi_txt)

        # Top border (under HUD)
        self.oled.hline(0, self.HUD_H - 1, self.oled.width, 1)

    def render(self):
        self.oled.fill(0)

        # HUD
        self._draw_hud()

        # Food (offset by HUD)
        fx, fy = self.food
        self.oled.fill_rect(fx*self.CELL, self.GRID_Y0 + fy*self.CELL, self.CELL, self.CELL, 1)

        # Snake
        for i, (x, y) in enumerate(self.snake):
            px = x * self.CELL
            py = self.GRID_Y0 + y * self.CELL
            if i == 0:
                self.oled.fill_rect(px, py, self.CELL, self.CELL, 1)
            else:
                self.oled.rect(px, py, self.CELL, self.CELL, 1)

        # Overlays
        if self.paused:
            self._overlay_center("PAUSED")
        elif self.game_over:
            self._overlay_gameover()

        # --- Draw playfield borders LAST so they stay visible ---
        # Left/right verticals span the full playfield height.
        self.oled.vline(self.x_left,  self.y_top, self.y_bot - self.y_top + 1, 1)
        self.oled.vline(self.x_right, self.y_top, self.y_bot - self.y_top + 1, 1)
        # Bottom border
        self.oled.hline(0, self.y_bot, self.oled.width, 1)

        self.oled.show()

    def _overlay_center(self, text):
        """Draw a single-line centered overlay; safely clamps width."""
        pad = 2
        fh = wri6.font.height()
        max_text_w = self.oled.width - 2 * pad

        # Clamp/ellipsize if too wide
        if wri6.stringlen(text) > max_text_w:
            base = text
            while base and wri6.stringlen(base + "...") > max_text_w:
                base = base[:-1]
            text = (base + "...") if base else "..."

        tw = wri6.stringlen(text)
        box_w = min(self.oled.width, tw + 2 * pad)
        box_h = fh + 2 * pad

        x = (self.oled.width - box_w) // 2
        if x < 0: x = 0
        y = self.GRID_Y0 + (self.GRID_H * self.CELL - box_h) // 2
        if y < self.GRID_Y0: y = self.GRID_Y0

        # box
        self.oled.fill_rect(x, y, box_w, box_h, 0)
        self.oled.rect(x, y, box_w, box_h, 1)

        # text
        tw = wri6.stringlen(text)  # recalc in case truncated
        tx = x + (box_w - tw) // 2
        if tx < 0: tx = 0
        wri6.set_textpos(self.oled, y + pad, tx)
        wri6.printstring(text)

    def _overlay_gameover(self):
        """Two-line centered overlay that always fits."""
        lines = ["GAME OVER", "SELECT=Restart"]
        pad = 2
        gap = 1
        fh = wri6.font.height()

        # Ellipsize each line if needed
        trimmed = []
        for s in lines:
            if wri6.stringlen(s) <= self.oled.width - 2 * pad:
                trimmed.append(s)
            else:
                base = s
                while base and wri6.stringlen(base + "...") > self.oled.width - 2 * pad:
                    base = base[:-1]
                trimmed.append((base + "...") if base else "...")
        lines = trimmed

        max_line_w = max(wri6.stringlen(s) for s in lines)
        box_w = min(self.oled.width, max_line_w + 2 * pad)
        box_h = 2 * fh + gap + 2 * pad

        x = (self.oled.width - box_w) // 2
        if x < 0: x = 0
        y = self.GRID_Y0 + (self.GRID_H * self.CELL - box_h) // 2
        if y < self.GRID_Y0: y = self.GRID_Y0

        # box
        self.oled.fill_rect(x, y, box_w, box_h, 0)
        self.oled.rect(x, y, box_w, box_h, 1)

        # lines
        ty = y + pad
        for s in lines:
            tw = wri6.stringlen(s)
            tx = x + (box_w - tw) // 2
            if tx < 0: tx = 0
            wri6.set_textpos(self.oled, ty, tx)
            wri6.printstring(s)
            ty += fh + gap

    # ---------- input ----------
    async def handle_button(self, btn):
        if not self.game_over and not self.paused:
            if btn == BTN_NEXT:
                self._turn_right()
            elif btn == BTN_PREV:
                self._turn_left()

        if btn == BTN_SELECT:
            if self.game_over:
                # cancel old loop before restart
                try:
                    if self._task:
                        self._task.cancel()
                        await asyncio.sleep_ms(0)
                except Exception:
                    pass
                # re-init fresh
                self.__init__(self.oled)
                return self
            else:
                self.paused = not self.paused
                self.render()
                return self

        if btn == BTN_BACK:
            self.running = False
            try:
                if self._task:
                    self._task.cancel()
            except Exception:
                pass
            return MenuScreen(self.oled)

        return self

# -----------------------
# Menu screen
# -----------------------

class MenuScreen(Screen):
    items = [("About", AboutScreen),
             ("Utils", UtilsScreen),
             ("Lights", LightsScreen),
             ("Snake", SnakeScreen),
             ("Gallery", GalleryScreen)]

    def __init__(self, oled):
        super().__init__(oled)
        self.index = 0
        self.render()

    def render(self):
        self.oled.fill(0)
        wri20.set_textpos(self.oled, 17, 20)
        wri20.printstring(MenuScreen.items[self.index][0])
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.index = (self.index+1) % len(MenuScreen.items)
            self.render()
        elif btn == BTN_PREV:
            self.index = (self.index-1) % len(MenuScreen.items)
            self.render()
        elif btn == BTN_SELECT:
            return MenuScreen.items[self.index][1](self.oled)
        return self

# -----------------------
# NeoPixel effects
# -----------------------
def hsv_to_rgb(h, s, v):
    """Convert hue [0–360], saturation [0–1], value [0–1] to RGB tuple."""
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return (int((r + m) * 255),
            int((g + m) * 255),
            int((b + m) * 255))

def led_eff_off(np, oldstate):
    np.fill((0,0,0))
    return oldstate

def led_eff_rainbow(np, oldstate):
    """Rainbow running around the circle"""
    pos = oldstate or 0
    for i in range(len(np)):
        pixel_hue = ((i * 360 // len(np)) + pos) % 360
        np[i] = hsv_to_rgb(pixel_hue, led_sat.value/100, led_brightness.value/100)
    return (pos + led_speed.value/10) % 360

def led_eff_rainbow2(np, oldstate):
    """Trans flag"""
    pos = oldstate or 0
    n = len(np)

    # Define flag colors (hue, saturation)
    white = (0, 0)
    pink = (348, led_sat.value / 100)
    cyan = (197, led_sat.value / 100)
    cls = [cyan, cyan, pink, pink, white, white, pink, pink, cyan, cyan, pink, pink, white, white, pink]

    for i in range(n):
        # Determine which of the 8 bands this LED is in
        band_idx = (i + int(pos / 30)) % len(cls)
        hue, sat = cls[band_idx]
        np[i] = hsv_to_rgb(hue, sat, led_brightness.value / 100)

    # advance rotation
    return (pos + led_speed.value / 10) % 360


def led_eff_breathe(np, oldstate):
    """All LEDs smoothly brighten and dim"""
    br, d = oldstate or (0, 1)
    rgb = hsv_to_rgb(led_hue.value, led_sat.value/100, br*led_brightness.value/100)

    for i in range(len(np)):
        np[i] = rgb
    br += d * led_speed.value / 1000
    if br >= 1.0:
        br = 1.0
        d = -1
    elif br <= 0.0:
        br = 0.0
        d = 1
    return (br, d)

def led_eff_comet(np, oldstate, tail=5):
    """Single bright dot with fading tail"""
    state = oldstate or 0
    head_idx = int(state) % len(np)
    fade_coeff = 0.5 + ((led_speed.maxval - led_speed.value) / led_speed.maxval * 0.4)
    # fade all LEDs slightly
    for i in range(len(np)):
        np[i] = tuple(int(x * fade_coeff) for x in np[i])
    # light the comet head
    np[head_idx] = hsv_to_rgb(led_hue.value, led_sat.value/100, led_brightness.value/100)
    
    return state + led_speed.value / 100


def led_eff_galery(np, oldstate, screen: GalleryScreen):
    for i in range(len(np)):
        np[i] = [int(u * led_brightness.value/100) for u in screen.colors[screen.index][i]]
    return oldstate


def led_eff_startup(np, oldstate):
    head, phase = oldstate or (0, 0)

    rgb_on = hsv_to_rgb(led_hue.value, led_sat.value/100, led_brightness.value/100)
    rgb_off = (0,0,0)
    for i in range(len(np)):
        rgb = rgb_on if (i <= head) == (phase == 0) else rgb_off
        np[i] = rgb
    
    if head < len(np) - 1:
        return (head + 1, phase)
    elif phase == 0:
        return (0, 1)
    else:
        return None


def led_eff_autocycle(np, oldstate):
    """
    Automatically cycles through all effects every minute.
    Reuse the existing led_effect functions one by one.
    """
    state = oldstate or {"idx": 1, "timer": time.ticks_ms(), "inner": None}
    now = time.ticks_ms()

    # every 60 seconds go to next effect (skip index 0 = Off)
    if time.ticks_diff(now, state["timer"]) > 60_000:
        state["idx"] += 1
        if state["idx"] >= len(led_effects):
            state["idx"] = 1        # wrap around, stay above 0
        state["timer"] = now
        state["inner"] = None       # reset inner effect state

    # run the current inner effect
    effect_fn = led_effects[state["idx"]][1]
    state["inner"] = effect_fn(np, state["inner"])
    return state


def led_eff_rainbow_comet(np, oldstate):
    """
    A comet that runs around the ring while its color cycles through the rainbow.
    The trail fades naturally, preserving past hues for a multicolor tail.
    """
    # state keeps a sub-pixel position and a hue
    state = oldstate or {"pos": 0.0, "hue": 0}

    # Where's the head right now?
    head_idx = int(state["pos"]) % len(np)

    # Fade existing LEDs slightly to create a tail
    # Faster speed -> slightly less fade; slower speed -> more persistence
    fade_coeff = 0.5 + ((led_speed.maxval - led_speed.value) / led_speed.maxval * 0.4)
    for i in range(len(np)):
        r, g, b = np[i]
        np[i] = (int(r * fade_coeff), int(g * fade_coeff), int(b * fade_coeff))

    # Set the head with the current rainbow hue
    rgb = hsv_to_rgb(state["hue"], led_sat.value/100, led_brightness.value/100)
    np[head_idx] = rgb

    # Advance position and hue based on Speed
    state["pos"] += led_speed.value / 100     # movement per frame
    state["hue"] = (state["hue"] + max(1, int(led_speed.value / 10))) % 360

    return state


def led_eff_ping_pong(np, oldstate):
    """
    Two bouncing heads with fading tails (like a KITT/Cylon sweep on a ring).
    """
    n = len(np)
    state = oldstate or {"pos": 0.0, "dir": 1}

    # Fade existing pixels for trailing effect
    fade = 0.5 + ((led_speed.maxval - led_speed.value) / led_speed.maxval * 0.4)
    for i in range(n):
        r, g, b = np[i]
        np[i] = (int(r * fade), int(g * fade), int(b * fade))

    # Primary head position (linear, reflecting at ends)
    pos = state["pos"]
    dir_ = state["dir"]
    speed = max(0.05, led_speed.value / 100)  # movement per frame
    pos += dir_ * speed
    if pos <= 0:
        pos = 0
        dir_ = 1
    elif pos >= n - 1:
        pos = n - 1
        dir_ = -1

    head1 = int(pos)
    # Second head mirrors across the strip ends
    head2 = (n - 1) - head1

    rgb = hsv_to_rgb(led_hue.value, led_sat.value/100, led_brightness.value/100)
    np[head1] = rgb
    np[head2] = rgb

    state["pos"], state["dir"] = pos, dir_
    return state


def led_eff_dual_hue(np, oldstate):
    """
    Opposite halves blend Hue -> Hue+180, rotating slowly.
    """
    state = oldstate or {"phase": 0.0}
    n = len(np)

    hue_a = led_hue.value % 360
    hue_b = (hue_a + 180) % 360
    s = led_sat.value / 100
    v = led_brightness.value / 100

    for i in range(n):
        # angle around ring with a rotating offset
        a = (2 * math.pi * i / n) + state["phase"]
        # smooth, mirrored gradient: 1 on one side, 0 on the opposite side
        m = 0.5 * (1 + math.cos(a))  # 1..0..1 around the circle
        # interpolate hue between A and B by m
        # (distance <= 180 so simple lerp is fine)
        hue = (hue_a * m + hue_b * (1 - m)) % 360
        np[i] = hsv_to_rgb(hue, s, v)

    # rotate divider; Speed controls rotation rate
    state["phase"] += led_speed.value / 400.0
    return state


def led_eff_aurora(np, oldstate):
    """
    Northern-lights style waves in green and purple.
    """
    state = oldstate or {"p1": 0.0, "p2": 0.0}
    n = len(np)

    hue_g = 130   # green-ish
    hue_p = 280   # purple-ish
    s = (led_sat.value / 100) * 0.9
    v_max = led_brightness.value / 100

    for i in range(n):
        x = 2 * math.pi * i / n
        # two gentle, offset waves
        w1 = 0.5 * (1 + math.sin(x + state["p1"]))       # 0..1
        w2 = 0.5 * (1 + math.sin(2 * x - state["p2"]))   # 0..1

        # color mix and brightness breathing
        mix = 0.6 * w1 + 0.4 * (1 - w2)                  # 0..1
        hue = (hue_g * mix + hue_p * (1 - mix)) % 360
        v = (0.25 + 0.75 * (0.5 * (1 + math.sin(x*0.8 + state["p2"]/2)))) * v_max

        np[i] = hsv_to_rgb(hue, s, v)

    # slow evolving phases; Speed affects flow
    sp = max(0.05, led_speed.value / 200.0)
    state["p1"] += sp * 0.6
    state["p2"] += sp * 0.3
    return state


def led_eff_spiral_spin(np, oldstate):
    """
    Rotating brightness wave around the ring, giving a spiral illusion.
    """
    state = oldstate or {"phase": 0.0}
    n = len(np)
    waves = 2  # try 1, 2, or 3 for different looks
    gamma = 1.6  # contrast

    s = led_sat.value/100
    v_base = led_brightness.value/100
    hue = led_hue.value

    for i in range(n):
        # normalized position around the ring
        t = (i / n) * (2 * math.pi * waves) + state["phase"]
        b = 0.5 * (1 + math.sin(t))              # 0..1
        b = b ** gamma                           # contrast curve
        r, g, b_rgb = hsv_to_rgb(hue, s, v_base * b)
        np[i] = (r, g, b_rgb)

    # Rotate the wave; speed controls angular velocity
    state["phase"] += (led_speed.value / 200)    # tweak feel here
    return state


async def neopixel_task(np):
    global led_effect
    global led_effects
    global led_startup
    global screen
    t = None
    prev_effect = 0
    led_effects = [("Off", led_eff_off),
                   ("Rainbow", led_eff_rainbow),
                   ("Rainbow2", led_eff_rainbow2),
                   ("Breathe", led_eff_breathe),
                   ("Comet", led_eff_comet),
                   ("Rainbow Comet", led_eff_rainbow_comet),
                   ("Ping-Pong", led_eff_ping_pong),
                   ("Dual Hue", led_eff_dual_hue),
                   ("Aurora", led_eff_aurora),
                   ("Spiral Spin", led_eff_spiral_spin),
                   ("Cycle_All", led_eff_autocycle)]

    while True:
        if led_startup == True:
            t = led_eff_startup(np, t)
            if t == None:
                led_startup = False
        else:
            if prev_effect != led_effect.value:
                t = None
                prev_effect = led_effect.value
            if led_effect.value in range(len(led_effects)):
                t = led_effects[led_effect.value][1](np, t)
            if isinstance(screen, GalleryScreen):
                t = led_eff_galery(np, t, screen)

        np.write()
        await asyncio.sleep_ms(int(1000/NEOPIXEL_FPS))

# -----------------------
# UI manager
# -----------------------
screen = None

async def ui_task(oled):
    global screen

    while True:
        await button_event.wait()
        button_event.clear()
        btn = last_button
        if screen == None:
            screen = MenuScreen(oled)
        screen = await screen.handle_button(btn)

        # Only auto-render non-Snake screens
        if not isinstance(screen, SnakeScreen):
            screen.render()

def wrap_text(text, writer, max_width, max_height):
    line_height = writer.font.height()
    max_rows = max_height // line_height

    words = text.split()
    lines, line = [], ""

    for word in words:
        # if a word itself is too long, split it at character level
        while writer.stringlen(word) > max_width:
            for i in range(1, len(word) + 1):
                if writer.stringlen(word[:i]) > max_width:
                    lines.append(word[:i-1])
                    word = word[i-1:]
                    break
        test_line = (line + " " + word).strip()
        if writer.stringlen(test_line) <= max_width:
            line = test_line
        else:
            lines.append(line)
            line = word
        if len(lines) >= max_rows:
            break
    if line and len(lines) < max_rows:
        lines.append(line)

    # truncate if too many lines
    if len(lines) > max_rows:
        lines = lines[:max_rows]
        # replace last line with ellipsis if there’s space
        if writer.stringlen(lines[-1] + "...") <= max_width:
            lines[-1] += "..."
        else:
            lines[-1] = lines[-1][:-3] + "..."

    return lines

def show_username(oled, name):
    global username_lines
    oled.fill(0)

    if not username_lines:
        username_lines = wrap_text(name, username_wri, oled.width, oled.height)
    total_height = len(username_lines) * username_wri.font.height()
    y = (oled.height - total_height) // 2

    for line in username_lines:
        x = (oled.width - username_wri.stringlen(line)) // 2
        username_wri.set_textpos(oled, y, x)
        username_wri.printstring(line)
        y += username_wri.font.height()

    oled.show()

async def inactivity_task(oled):
    global screen

    while True:
        await asyncio.sleep_ms(500)
        inactive = (screen == None or isinstance(screen, MenuScreen)) and \
                   time.ticks_diff(time.ticks_ms(), last_activity) > INACTIVITY_TIMEOUT
        if inactive:
            show_username(oled, USERNAME)


# -----------------------
# Main
# -----------------------
async def main():
    global button_event, last_activity
    np = init_neopixels()
    button_event = asyncio.Event()
    last_activity = time.ticks_ms()

    setup_buttons()
    load_params()
    print("Modded badge posts!")

    await asyncio.gather(ui_task(oled), inactivity_task(oled), neopixel_task(np))

try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
