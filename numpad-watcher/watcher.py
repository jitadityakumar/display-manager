#!/usr/bin/env python3
"""
Numpad watcher for display-manager kiosk.

State machine:
  off        -> any key       -> wake monitor + show menu  -> menu
  menu       -> digit         -> buffer digit
  menu       -> enter         -> select buffered URL        -> displaying
  menu       -> 5-min timeout -> sleep monitor              -> off
  displaying -> backspace     -> show menu                  -> menu
  displaying -> 15-min timeout-> sleep monitor              -> off
"""
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import evdev

DEVICE      = '/dev/input/event14'
API         = 'http://localhost:8080'
MENU_SECS   = 5 * 60
DISPLAY_SECS = 15 * 60

IGNORE  = {'KEY_NUMLOCK'}
DIGITS  = {
    'KEY_KP1': 1, 'KEY_KP2': 2, 'KEY_KP3': 3,
    'KEY_KP4': 4, 'KEY_KP5': 5, 'KEY_KP6': 6,
    'KEY_KP7': 7, 'KEY_KP8': 8, 'KEY_KP9': 9,
}

state   = 'off'
digit   = None
_timer  = None
_lock   = threading.Lock()


# --- display control ---

def wake():
    subprocess.run(['bash', '-c', 'DISPLAY=:0 xset dpms force on && DISPLAY=:0 xset -dpms'], capture_output=True)

def sleep_display():
    subprocess.run(['bash', '-c', 'DISPLAY=:0 xset dpms force off'], capture_output=True)


# --- API helpers ---

def api_get():
    try:
        with urllib.request.urlopen(f'{API}/api/config', timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None

def api_put(**kwargs):
    try:
        data = json.dumps(kwargs).encode()
        req  = urllib.request.Request(
            f'{API}/api/config', data=data, method='PUT',
            headers={'Content-Type': 'application/json'},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


# --- timer helpers ---

def _cancel_timer():
    global _timer
    if _timer:
        _timer.cancel()
        _timer = None

def _start_timer(secs, fn):
    global _timer
    _cancel_timer()
    _timer = threading.Timer(secs, fn)
    _timer.daemon = True
    _timer.start()


# --- state transitions ---

def _on_menu_timeout():
    with _lock:
        global state
        state = 'off'
    api_put(menu_active=False)
    sleep_display()
    print('menu timeout → off')

def _on_display_timeout():
    with _lock:
        global state
        state = 'off'
    api_put(menu_active=False)
    sleep_display()
    print('display timeout → off')

def enter_menu():
    global state, digit
    state = 'menu'
    digit = None
    api_put(menu_active=True)
    _start_timer(MENU_SECS, _on_menu_timeout)
    print('→ menu')

def handle_key(keycode):
    global state, digit  # noqa: PLW0603

    if keycode in IGNORE:
        return

    with _lock:
        current = state

    print(f'[{current}] {keycode}')

    if current == 'off':
        wake()
        with _lock:
            enter_menu()
        return

    if current == 'menu':
        if keycode in DIGITS:
            with _lock:
                digit = DIGITS[keycode]
            print(f'  buffered digit: {digit}')

        elif keycode == 'KEY_KPENTER':
            with _lock:
                selected = digit
                digit = None
            if selected is None:
                return
            cfg = api_get()
            if not cfg:
                return
            urls = cfg.get('urls', [])
            idx  = selected - 1
            if not (0 <= idx < len(urls)):
                print(f'  digit {selected} out of range ({len(urls)} urls)')
                return
            url = urls[idx]
            api_put(menu_active=False, mode='single', active_url_id=url['id'])
            with _lock:
                state = 'displaying'
            _start_timer(DISPLAY_SECS, _on_display_timeout)
            print(f'→ displaying: {url["label"]}')

        return

    if current == 'displaying':
        if keycode == 'KEY_BACKSPACE':
            with _lock:
                enter_menu()
        return


def main():
    try:
        dev = evdev.InputDevice(DEVICE)
    except FileNotFoundError:
        print(f'error: device {DEVICE} not found', file=sys.stderr)
        sys.exit(1)

    dev.grab()
    print(f'watching {dev.name} ({DEVICE})')

    try:
        for event in dev.read_loop():
            if event.type == evdev.ecodes.EV_KEY:
                k = evdev.categorize(event)
                if k.keystate == evdev.KeyEvent.key_down:
                    handle_key(k.keycode)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            dev.ungrab()
        except Exception:
            pass


if __name__ == '__main__':
    main()
