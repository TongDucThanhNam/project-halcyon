"""Bounded ordinary Android input without one VM startup per gesture.

The external dex must be built from Tools/android/HalcyonInput.java. This
adapter changes only tap/swipe transport; scenario focus/native/wire guards
remain mandatory. A DONE receipt is not client acceptance or a game ack.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


class InputBridge:
    def __init__(self, adb, dex, output):
        self.adb, self.dex, self.output = adb, Path(dex), Path(output)
        self.process = None
        self.sequence = 0
        self.lines = queue.Queue()
        self.remote = None
        self.journal = None

    def __getattr__(self, name):
        return getattr(self.adb, name)

    def start(self):
        if self.adb.wm_size() != (960, 540):
            raise ValueError('input bridge requires qualified960x540 viewport')
        manifest = json.loads(self.dex.with_suffix('.build.json').read_text())
        source = Path(__file__).with_name('android')/'HalcyonInput.java'
        digest = hashlib.sha256(self.dex.read_bytes()).hexdigest()
        if manifest['dex_sha256'] != digest or manifest['source_sha256'] != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('input bridge source/build identity mismatch')
        self.remote = '/data/local/tmp/halcyon-input-' + digest[:20] + '.dex'
        pushed = self.adb._run('push', str(self.dex), self.remote)
        if pushed.returncode:
            raise RuntimeError('input bridge push failed')
        if self.adb.shell('sha256sum ' + self.remote).split()[0] != digest:
            raise RuntimeError('input bridge device digest mismatch')
        self.journal = self.output.open('x', encoding='utf-8')
        self._write({'event': 'start', 'manifest': manifest, 'serial': self.adb.serial,
                     'device_input_sha256': self.adb.shell('sha256sum /system/framework/input.jar').split()[0]})
        self.stderr = self.output.with_suffix('.stderr.log').open('x', encoding='utf-8')
        self.process = subprocess.Popen(['adb', '-s', self.adb.serial, 'shell', '-T',
            'CLASSPATH=' + self.remote + ':/system/framework/input.jar app_process /system/bin HalcyonInput'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding='utf-8', bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            if self._line(10) != 'HALCYON_INPUT_V1':
                raise RuntimeError('input bridge handshake changed')
            self.ping()
        except BaseException:
            self.close()
            raise
        return self

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def _line(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError('ordinary input bridge response timed out; do not retry') from exc
        if line is None:
            raise RuntimeError('ordinary input bridge exited')
        return line

    def _write(self, row):
        self.journal.write(json.dumps(row, separators=(',', ':'))+'\n')
        self.journal.flush()

    def _command(self, command):
        self.sequence += 1
        before, mono = time.time(), time.monotonic_ns()
        self._write({'event': 'attempt', 'sequence': self.sequence, 'command': command,
                     'wall_before': before, 'monotonic_before_ns': mono})
        self.process.stdin.write(str(self.sequence)+' '+command+'\n')
        self.process.stdin.flush()
        words = self._line(5).split()
        if len(words) != 4 or words[:2] != ['DONE', str(self.sequence)]:
            raise RuntimeError('input bridge sequence/receipt changed')
        self._write({'event': 'done', 'sequence': self.sequence, 'wall_after': time.time(),
                     'host_elapsed_ms': (time.monotonic_ns()-mono)/1e6,
                     'guest_started_ns': int(words[2]), 'guest_ended_ns': int(words[3])})

    @staticmethod
    def _point(x, y):
        if type(x) is not int or type(y) is not int or not (0 <= x < 960 and 0 <= y < 540):
            raise ValueError('unqualified input coordinate')

    def ping(self):
        self._command('P')

    def tap(self, x, y):
        self._point(x, y)
        self._command(f'T {x} {y}')

    def swipe(self, x1, y1, x2, y2, *, duration_ms=250):
        self._point(x1, y1)
        self._point(x2, y2)
        if type(duration_ms) is not int or not 1 <= duration_ms <= 2000:
            raise ValueError('unqualified swipe duration')
        self._command(f'S {x1} {y1} {x2} {y2} {duration_ms}')

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process.stdout.close()
            self.stderr.close()
            self.process = None
        if self.journal is not None:
            self._write({'event': 'close', 'wall': time.time()})
            self.journal.close()
            self.journal = None
