#!/usr/bin/env python3
import json
import subprocess
import sys
import time
import urllib.request

API          = 'http://localhost:8080'
POLL_SECS    = 2
MAX_BACKOFF_SECS = 60


def _get_restart_status():
    with urllib.request.urlopen(f'{API}/api/restart', timeout=3) as r:
        return json.loads(r.read())


def _ack_restart():
    req = urllib.request.Request(f'{API}/api/restart/ack', method='POST')
    urllib.request.urlopen(req, timeout=3)


def main():
    print('watching for kiosk restart requests')
    consecutive_failures = 0
    while True:
        try:
            status = _get_restart_status()
            if status.get('pending'):
                print('restart requested, running systemctl restart kiosk')
                subprocess.run(['sudo', 'systemctl', 'restart', 'kiosk'], check=True)
                _ack_restart()
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            print(f'error (attempt {consecutive_failures}): {e}', file=sys.stderr)
        backoff = min(POLL_SECS * (2 ** consecutive_failures), MAX_BACKOFF_SECS)
        time.sleep(backoff)


if __name__ == '__main__':
    main()
