"""Exercise in-session synchronization in real curses, with an isolated fake API.

Run with the same Python environment as tasks-tui:
    python tests/tui_sync_pty.py
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch
from tasks_tui.main import cli

cached = {'task_lists': [{'id': 'list', 'title': 'Test list'}],
          'tasks': {'list': [{'id': 'task', 'title': 'Cached task'}]}}
api = Mock()
api.tasklists.return_value.list.return_value.execute.return_value = {
    'items': cached['task_lists']}
api.tasks.return_value.list.return_value.execute.side_effect = [
    {'items': [{'id': 'task', 'title': 'Startup task'}]},
    {'items': [{'id': 'task', 'title': 'Phone task'}]},
    OSError('Offline smoke test'),
    {'items': [{'id': 'task', 'title': 'Recovered task'}]},
    {'items': [{'id': 'task', 'title': 'Recovered task'}]},
]
api.tasks.return_value.patch.return_value.execute.side_effect = lambda: Path(sys.argv[1]).write_text(
    json.dumps(api.tasks.return_value.patch.call_args.kwargs))
with patch('tasks_tui.task_service.get_credentials'), \
     patch('tasks_tui.task_service.build', return_value=api), \
     patch('tasks_tui.task_service.local_storage.load_data', return_value=cached), \
     patch('tasks_tui.task_service.local_storage.save_data'):
    cli([])
assert api.tasks.return_value.list.call_count == 5
api.tasks.return_value.patch.assert_called_once_with(
    tasklist='list', task='task', body={'title': 'Recovered task edited'})
print('SYNC_SMOKE_OK', flush=True)
'''


def main():
    temp = tempfile.TemporaryDirectory()
    receipt = Path(temp.name) / 'uploaded.json'
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
    env = dict(os.environ, TERM='xterm-256color', PYTHONPATH=str(ROOT))
    child = subprocess.Popen([sys.executable, '-c', CHILD, str(receipt)], stdin=slave,
                             stdout=slave, stderr=slave, env=env, cwd=ROOT)
    os.close(slave)
    output = bytearray()

    def wait_for(expected, start=0):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if expected in output[start:]:
                return
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        raise AssertionError(f'Missing {expected!r}; terminal tail: {output[-1500:]!r}')

    def send(data, expected):
        start = len(output)
        os.write(master, data)
        wait_for(expected, start)

    try:
        wait_for(b'Startup task')
        send(b'?', b'Sync with Google Tasks')
        # Curses need not redraw unchanged text when the help overlay closes.
        send(b'?r', b'Phone')
        send(b'w', b'Sync failed: Offline smoke test')
        send(b'r', b'Recovered task')
        send(b'le', b'Edit task')
        send(b' edited\r', b'Syncing')
        # Confirm the upload completed without pressing sync or quitting.
        deadline = time.monotonic() + 5
        while not receipt.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert json.loads(receipt.read_text()) == {
            'tasklist': 'list', 'task': 'task', 'body': {'title': 'Recovered task edited'}}
        send(b'q', b'SYNC_SMOKE_OK')
        child.wait(timeout=5)
        assert child.returncode == 0, output.decode(errors='replace')
        assert b'Traceback' not in output, output.decode(errors='replace')
        print('PASS: real curses startup, help, manual fetch, offline retry, automatic upload, and quit')
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        temp.cleanup()


if __name__ == '__main__':
    main()
