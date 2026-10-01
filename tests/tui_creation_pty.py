"""Real curses smoke test, isolated from Google and the user's task cache.

Run with the same Python environment as tasks-tui:
    python tests/tui_creation_pty.py
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import json
import sys
from datetime import date, timedelta
from unicurses import wrapper, cbreak, noecho
from tasks_tui.ui_manager import UIManager

def run(screen):
    cbreak()
    noecho()
    ui = UIManager(screen)
    results = [ui.task_form(), ui.task_form(), ui.task_form(),
               ui.pick_date('2026-12-31'), ui.pick_date('2026-09-25'),
               ui.task_form(),
               ui.task_form({'title': 'Existing', 'due': '2026-09-25T00:00:00Z'})]
    with open(sys.argv[1], 'w') as output:
        json.dump(results, output)
wrapper(run)
'''


def main():
    with tempfile.TemporaryDirectory() as temp:
        result_path = Path(temp) / 'result.json'
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        env = dict(os.environ, TERM='xterm-256color', PYTHONPATH=str(ROOT), ESCDELAY='25')
        child = subprocess.Popen([sys.executable, '-c', CHILD, str(result_path)],
                                 stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT)
        os.close(slave)
        output = bytearray()

        def drain():
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if not select.select([master], [], [], 0.15)[0]:
                    return
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    return

        def send(data):
            os.write(master, data)
            drain()

        try:
            # Wait for the first form (imports can be slower on a cold start).
            deadline = time.monotonic() + 10
            while b'New task' not in output and time.monotonic() < deadline:
                drain()
            assert b'New task' in output, output.decode(errors='replace')
            send('Café 🚀\r'.encode())
            send(b'Tomorrow task\t\t\t\r\r')
            send(b'Calendar draft\t\t\t\t\r')
            assert b'Choose date' in output
            send(b'\x1b')  # Cancel calendar only; title must survive.
            # Shrink then restore while the draft is open.
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 10, 40, 0, 0))
            child.send_signal(signal.SIGWINCH)
            drain()
            assert b'Enlarge terminal' in output
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
            child.send_signal(signal.SIGWINCH)
            drain()
            send(b'\t\r')  # Save the preserved draft.
            send(b'\tl\r')  # Dec 31 -> Jan 1.
            send(b'n')  # Clear an existing date.
            send(b'Never saved\x1b')
            assert b'Edit task' in output
            send(b' edited\tn\r')
            child.wait(timeout=5)
            assert child.returncode == 0, output.decode(errors='replace')
            results = json.loads(result_path.read_text())
            from datetime import date, timedelta
            assert results == [
                {'title': 'Café 🚀', 'due': ''},
                {'title': 'Tomorrow task', 'due': (date.today()+timedelta(days=1)).isoformat()},
                {'title': 'Calendar draft', 'due': ''},
                '2027-01-01', '', None,
                {'title': 'Existing edited', 'due': ''},
            ], results
            print('PASS: real curses creation, editing, Unicode, tomorrow, calendar, cancel, clear, and resize')
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)


if __name__ == '__main__':
    main()
