"""Owned production-default protocol server, in-process or in a dedicated child.

The child owns gateway/match threads, journal and server telemetry. Its stdin is
only a shutdown lease, never a gameplay/preparation channel. Participants still
use ordinary gateway sockets. Readiness and close receipts are atomic on disk.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SetupFailure(RuntimeError):
    def __init__(self, failures):
        self.failures = failures
        super().__init__('; '.join(failures))


def write_receipt(path, value):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, indent=2), encoding='utf-8')
    pending.replace(path)


class LocalServer:
    def __init__(self, host, match_id, output, *, journal=False, telemetry=False,
                 role='combined'):
        from Tools.protocol_participants import private_host
        self.host = private_host(host)
        if not ipaddress.ip_address(self.host).is_loopback:
            raise ValueError('owned self-host server binds loopback only')
        self.match_id, self.output = match_id, Path(output)
        self.journal_enabled, self.telemetry_enabled, self.role = journal, telemetry, role
        self.gateway = self.telemetry = self.result = None
        self.environment = None
        self.log_lock = threading.Lock()

    def log(self, line):
        with self.log_lock, (self.output/'server.log').open('a', encoding='utf-8') as log:
            log.write(f'{time.time():.6f} {line}\n')

    def start(self):
        if self.environment is not None or self.result is not None:
            raise RuntimeError('LocalServer lifecycle may only be started once')
        from server import gateway, navigation, paths, wire, world_tape
        from Tools.run_scenarios import ISOLATED_ENVIRONMENT
        from Tools.verification_support import RUNTIME_SWITCHES
        from Tools.protocol_participants import source_identity
        self.source = source_identity()
        self.environment = {name:os.environ.get(name) for name in
                            ('HALCYON_INPUT_JOURNAL_DIR','HALCYON_TRACE_MOVEMENT')}
        try:
            if self.journal_enabled:
                os.environ['HALCYON_INPUT_JOURNAL_DIR'] = str(self.output)
                os.environ['HALCYON_TRACE_MOVEMENT'] = '1'
            required = (paths.stack_dir()/'world_tape.bin',
                        Path(os.environ.get('HALCYON_NAVMESH', navigation.DEFAULT_CLASSIC_NAVMESH)))
            allowed = {'HALCYON_INPUT_JOURNAL_DIR','HALCYON_TRACE_MOVEMENT','HALCYON_NAVMESH',
                       'HALCYON_LOCAL_ROOT','HALCYON_STACK_DIR','HALCYON_SPAWN_CORPUS','HALCYON_SKYE_VOLLEY_CORPUS'}
            failures = [f'missing: {path}' for path in required if not path.is_file()]
            failures += [f'nonproduction override: {name}'
                         for name in set(ISOLATED_ENVIRONMENT) | set(RUNTIME_SWITCHES) | {'HALCYON_NO_TAPE','HALCYON_NO_WAVE'}
                         if name not in allowed and os.environ.get(name)]
            if not failures:
                try:
                    navigation.load_halcyon_navmesh(required[1])
                    if not world_tape.load_tape(str(required[0]), skip_until_op=wire.OP.ENTITY_DATA):
                        failures.append(f'empty world tape: {required[0]}')
                except (ValueError, OSError) as exc:
                    failures.append(str(exc))
            if failures:
                raise SetupFailure(failures)
            self.inputs = {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in required}
            self.gateway = gateway.Gateway(self.host, 0, self.match_id, heartbeat_port=0, log=self.log)
            self.gateway.start()
            if self.telemetry_enabled:
                from Tools.protocol_telemetry import Telemetry
                self.telemetry = Telemetry(self.gateway, self.output, role=self.role)
                self.telemetry.start()
            self.ready = {'status':'READY', 'pid':os.getpid(), 'host':self.host,
                          'port':self.gateway.port, 'heartbeat_port':self.gateway.relay.port,
                          'inputs':self.inputs, 'source_sha256':self.source['manifest_sha256']}
            return self.ready
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.result is not None:
            return self.result
        from Tools.protocol_participants import source_identity
        failures, journals = [], []
        try:
            if self.telemetry is not None:
                self.telemetry.close()
                if self.telemetry.error:
                    failures.append('telemetry: '+self.telemetry.error)
            if self.gateway is not None:
                self.gateway.stop()
                for match in self.gateway.matches:
                    session = match.session
                    if session is None:
                        continue
                    session.join(timeout=10)
                    journal = session.journal
                    if self.journal_enabled:
                        journals.append({'path':str(journal.path) if journal else None,
                            'closed':journal.closed if journal else False,
                            'failure':journal.failure if journal else 'missing journal',
                            'records':journal.sequence if journal else 0,
                            'checkpoints':journal.checkpoint_count if journal else 0,
                            'thread_stopped':not session.is_alive()})
                    if session.is_alive():
                        failures.append('match thread did not stop')
            stable = not hasattr(self, 'source') or self.source['manifest_sha256'] == source_identity()['manifest_sha256']
            if not stable:
                failures.append('server source changed during run')
            if any(not r['closed'] or r['failure'] or not r['thread_stopped'] for r in journals):
                failures.append('input journal did not close successfully')
            self.result = {'status':'ERROR' if failures else 'PASS', 'pid':os.getpid(),
                'failures':failures, 'journals':journals, 'source_stable':stable,
                'telemetry_error':self.telemetry.error if self.telemetry else None}
            return self.result
        finally:
            if self.environment is not None:
                for name,value in self.environment.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value


class ServerProcess:
    """Bounded child lifecycle; no shell, inherited console or hidden retry."""
    def __init__(self, host, match_id, output, *, journal=False, telemetry=False):
        self.host, self.match_id, self.output = host, match_id, Path(output)
        self.journal, self.telemetry = journal, telemetry
        self.process = self.log_file = self.result = None

    def start(self, timeout=60):
        from Tools.protocol_participants import source_identity
        command = [sys.executable, '-B', str(Path(__file__).resolve()),
                   '--host', self.host, '--match-id', self.match_id, '--output', str(self.output)]
        command += ['--journal'] if self.journal else []
        command += ['--telemetry'] if self.telemetry else []
        environment = None
        if (sys.platform == 'win32'
                and os.path.normcase(sys.executable) != os.path.normcase(sys._base_executable)):
            # Match multiprocessing.popen_spawn_win32: the venv redirector
            # otherwise owns Popen.pid while a different PID runs the server.
            # Preserve the venv, but launch its interpreter directly so the
            # exact PID/source readiness guard and kill handle remain valid.
            command[0] = sys._base_executable
            environment = os.environ.copy()
            environment['__PYVENV_LAUNCHER__'] = sys.executable
        self.log_file = (self.output/'server-process.log').open('x', encoding='utf-8')
        try:
            self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE,
                stdout=self.log_file, stderr=subprocess.STDOUT, text=True, env=environment,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic()+timeout
            ready = self.output/'server-ready.json'
            while time.monotonic() < deadline:
                if ready.is_file():
                    self.ready = json.loads(ready.read_text(encoding='utf-8'))
                    if self.ready['pid'] != self.process.pid or self.ready['source_sha256'] != source_identity()['manifest_sha256']:
                        raise SetupFailure(['server readiness process/source mismatch'])
                    if self.process.poll() is not None:
                        break
                    return self.ready
                if self.process.poll() is not None:
                    break
                time.sleep(.05)
            failure = self.output/'server-startup-error.json'
            reasons = json.loads(failure.read_text(encoding='utf-8'))['failures'] if failure.is_file() else [
                f'server process did not become ready (exit={self.process.poll()})']
            raise SetupFailure(reasons)
        except BaseException:
            self.close()
            raise

    def close(self, timeout=30):
        if self.result is not None:
            return self.result
        failures = []
        try:
            if self.process is not None:
                if self.process.poll() is None and not self.process.stdin.closed:
                    try:
                        self.process.stdin.write('stop\n')
                        self.process.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    failures.append('server shutdown timed out; child killed, evidence incomplete')
                    self.process.kill()
                    self.process.wait(timeout=10)
                if self.process.returncode:
                    failures.append(f'server process exit {self.process.returncode}')
            receipt = self.output/'server-result.json'
            result = json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else {
                'status':'ERROR','failures':['missing server close receipt'],'journals':[]}
            result['failures'].extend(failures)
            result['exit_code'] = self.process.returncode if self.process else None
            if result['failures']:
                result['status'] = 'ERROR'
            self.result = result
            return result
        finally:
            if self.process is not None and self.process.stdin is not None:
                self.process.stdin.close()
            if self.log_file is not None:
                self.log_file.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--match-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--journal', action='store_true')
    parser.add_argument('--telemetry', action='store_true')
    args = parser.parse_args(argv)
    from Tools.verification_support import reject_link_traversal
    reject_link_traversal(args.output)
    output = args.output.resolve()
    if (ROOT/'Local/evidence').resolve() not in output.parents or not output.is_dir():
        parser.error('server child requires an existing evidence directory under Local/evidence')
    if any((output/name).exists() for name in ('server-ready.json','server-result.json','server-startup-error.json')):
        parser.error('server child refuses to overwrite previous process receipts')
    server = LocalServer(args.host, args.match_id, output, journal=args.journal,
                         telemetry=args.telemetry, role='server')
    failed = False
    try:
        write_receipt(output/'server-ready.json', server.start())
        command = sys.stdin.readline()
        if command not in ('stop\n', ''):
            raise ValueError('invalid server shutdown lease command')
    except Exception as exc:
        failed = True
        write_receipt(output/'server-startup-error.json', {
            'failures':exc.failures if isinstance(exc, SetupFailure) else [repr(exc)],
            'traceback':traceback.format_exc()})
    finally:
        result = server.close()
        write_receipt(output/'server-result.json', result)
    return 1 if failed or result['status'] != 'PASS' else 0


if __name__ == '__main__':
    raise SystemExit(main())
