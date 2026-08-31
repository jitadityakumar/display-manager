#!/usr/bin/env python3
import json
import subprocess
import sys
import time
import urllib.request

API          = 'http://localhost:8080'
POLL_SECS    = 2


def _get_restart_status():
    with urllib.request.urlopen(f'{API}/api/restart', timeout=3) as r:
        return json.loads(r.read())


def _ack_restart():
    req = urllib.request.Request(f'{API}/api/restart/ack', method='POST')
    urllib.request.urlopen(req, timeout=3)


def main():
    print('watching for kiosk restart requests')
    while True:
        try:
            status = _get_restart_status()
            if status.get('pending'):
                print('restart requested, running systemctl restart kiosk')
                subprocess.run(['sudo', 'systemctl', 'restart', 'kiosk'], check=True)
                _ack_restart()
        except Exception as e:
            print(f'error: {e}', file=sys.stderr)
        time.sleep(POLL_SECS)


if __name__ == '__main__':
    main()
