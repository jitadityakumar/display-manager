#!/usr/bin/env python3
import sys
import threading
import urllib.request

import evdev

DEVICE     = '/dev/input/event14'
API        = 'http://localhost:8080'
IDLE_SECS  = 20 * 60  # fallback sleep if JS timers don't fire
IGNORE     = {'KEY_NUMLOCK'}

_timer = None


def _api_monitor(action):
    try:
        data = f'{{"action":"{action}"}}'.encode()
        req = urllib.request.Request(
            f'{API}/api/monitor', data=data,
            headers={'Content-Type': 'application/json'},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def _reset_idle_timer():
    global _timer
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(IDLE_SECS, lambda: _api_monitor('sleep'))
    _timer.daemon = True
    _timer.start()


def main():
    try:
        dev = evdev.InputDevice(DEVICE)
    except FileNotFoundError:
        print(f'error: device {DEVICE} not found', file=sys.stderr)
        sys.exit(1)

    print(f'watching {dev.name} ({DEVICE})')

    try:
        for event in dev.read_loop():
            if event.type == evdev.ecodes.EV_KEY:
                k = evdev.categorize(event)
                if k.keystate == evdev.KeyEvent.key_down and k.keycode not in IGNORE:
                    _api_monitor('wake')
                    _reset_idle_timer()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
