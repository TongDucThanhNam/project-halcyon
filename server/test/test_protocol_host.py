"""Separate-process lifecycle, evidence ownership and failure classification."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from Tools import protocol_host as host, protocol_participants as pp
from Tools.protocol_telemetry import population_time_fit, summarize


class TestServerProcess(unittest.TestCase):
    def test_parent_pipe_eof_stops_owned_child_cleanly(self):
        output = pp.new_output()
        child = host.ServerProcess('127.0.0.1',pp.MATCH_ID,output)
        self.addCleanup(child.close)
        with patch.object(host.subprocess,'Popen',wraps=subprocess.Popen) as launched:
            ready = child.start()
        launches = [call for call in launched.call_args_list
                    if str(Path(host.__file__).resolve()) in call.args[0]]
        self.assertEqual(len(launches),1)
        if sys.platform == 'win32' and os.path.normcase(sys.executable) != os.path.normcase(sys._base_executable):
            self.assertEqual(launches[0].args[0][0],sys._base_executable)
            self.assertEqual(launches[0].kwargs['env']['__PYVENV_LAUNCHER__'],sys.executable)
        else:
            self.assertEqual(launches[0].args[0][0],sys.executable)
            self.assertIsNone(launches[0].kwargs['env'])
        self.assertEqual(ready['pid'],child.process.pid)
        self.assertEqual(ready['source_sha256'],pp.source_identity()['manifest_sha256'])
        self.assertNotEqual(ready['pid'],os.getpid())
        child.process.stdin.close()
        child.process.wait(timeout=15)
        result = child.close()
        self.assertEqual(result['status'],'PASS',result)
        self.assertEqual(result['exit_code'],0)
        self.assertTrue(result['source_stable'])

    def test_readiness_rejects_wrong_pid_or_source_without_weakening_guard(self):
        source = pp.source_identity()['manifest_sha256']
        for pid, digest in ((102,source),(101,'not-the-current-source')):
            with self.subTest(pid=pid,source=digest):
                output = pp.new_output()
                (output/'server-ready.json').write_text(json.dumps({
                    'status':'READY','pid':pid,'source_sha256':digest}))
                (output/'server-result.json').write_text(json.dumps({
                    'status':'PASS','pid':101,'failures':[],'journals':[]}))
                process = Mock(pid=101,returncode=0)
                process.poll.return_value = None
                process.stdin.closed = False
                child = host.ServerProcess('127.0.0.1',pp.MATCH_ID,output)
                with patch.object(host.subprocess,'Popen',return_value=process), \
                        patch.object(pp,'source_identity',return_value={'manifest_sha256':source}):
                    with self.assertRaisesRegex(host.SetupFailure,'process/source mismatch'):
                        child.start()
                process.wait.assert_called_once_with(timeout=30)
                process.stdin.close.assert_called_once()
                self.assertTrue(child.log_file.closed)

    def test_child_startup_failure_is_setup_and_leaves_no_child(self):
        output = pp.new_output()
        child = host.ServerProcess('127.0.0.1',pp.MATCH_ID,output)
        with patch.dict(os.environ, {'HALCYON_STACK_DIR':str(output/'missing-stack')}):
            with self.assertRaisesRegex(host.SetupFailure,'missing:'):
                child.start()
        self.assertIsNotNone(child.process.poll())
        self.assertFalse((output/'server-ready.json').exists())
        failure = json.loads((output/'server-startup-error.json').read_text())
        self.assertTrue(any('missing:' in row for row in failure['failures']))
        self.assertEqual(child.close()['status'],'ERROR')

    def test_shutdown_timeout_is_not_a_successful_close(self):
        output = pp.new_output()
        child = host.ServerProcess('127.0.0.1',pp.MATCH_ID,output)
        child.process = Mock(returncode=1)
        child.process.poll.return_value = None
        child.process.stdin.closed = False
        child.process.wait.side_effect = [subprocess.TimeoutExpired('fixture',.01),1]
        result = child.close(timeout=.01)
        self.assertEqual(result['status'],'ERROR')
        self.assertIn('server shutdown timed out; child killed, evidence incomplete',result['failures'])
        child.process.kill.assert_called_once()
        child.process.stdin.close.assert_called_once()
        self.assertIs(child.close(),result)

    def test_cli_requires_owned_self_host_for_process_mode(self):
        with self.assertRaises(SystemExit) as raised:
            pp.main(['--server-process'])
        self.assertEqual(raised.exception.code,2)

    def test_production_child_cli_journal_probe_and_both_process_telemetries(self):
        output = pp.new_output()/'cli'
        # Short integration fixture, NOT a shortened acceptance soak. The real
        # production bootstrap and six sockets run in the separate child. Only
        # this test's parent play sequence is bounded to one ordinary input.
        def short_play(players):
            p = players[0]
            p.send(1012, pp.struct.pack('>ff6x',25,40))
            deadline, offset, observed = time.monotonic()+90, 0, 0
            while time.monotonic() < deadline:
                with (output/'server.log').open(encoding='utf-8') as source:
                    source.seek(offset)
                    observed += source.read().count('[movement-tick] ')
                    offset = source.tell()
                if observed >= 3:
                    return
                time.sleep(.1)
            raise pp.StageFailure('integration fixture never observed production live ticks')
        with patch.dict(os.environ,{'HALCYON_CHECKPOINT_PROBE':'1'}), patch.object(pp,'play',short_play):
            code = pp.main(['--self-host','--server-process','--journal','--telemetry','--output',str(output)])
        summary = json.loads((output/'summary.json').read_text())
        (output/'unit-test-contract.json').write_text(json.dumps({
            'claim':'process/journal/probe/summarizer integration only; not gameplay or soak acceptance'}))
        self.assertEqual(code,0,summary)
        self.assertEqual(summary['status'],'PASS')
        self.assertTrue(summary['source_stable'])
        receipt = summary['server_process']
        self.assertTrue(receipt['isolated'])
        self.assertNotEqual(receipt['server_pid'],os.getpid())
        self.assertEqual(receipt['participant_pid'],os.getpid())
        self.assertEqual(receipt['close_receipt']['exit_code'],0)
        self.assertEqual(set(summary['process_telemetry']),{'server','participants'})
        for role,pid in (('server',receipt['server_pid']),('participants',os.getpid())):
            self.assertEqual(summary['process_telemetry'][role]['pid'],pid)
        self.assertEqual(len(summary['journals']),1)
        journal, = summary['journals']
        self.assertTrue(journal['closed'])
        self.assertTrue(journal['thread_stopped'])
        self.assertIsNone(journal['failure'])
        self.assertGreater(journal['records'],0)
        self.assertTrue(Path(journal['path']).with_suffix('.probe.json').is_file())
        self.assertEqual(list(output.glob('inputs-*.jsonl')),[Path(journal['path'])])
        self.assertTrue(list(output.glob('probe-inputs-*.measurements.jsonl')))
        self.assertTrue(Path(summary['journal_tick_anchors']).is_file())
        ticks = [json.loads(line.split('[movement-tick] ',1)[1])
                 for line in (output/'server.log').read_text().splitlines() if '[movement-tick] ' in line]
        self.assertTrue(ticks)
        self.assertTrue(all(row['thread_cpu_ms'] is not None and row['phase_timings'] for row in ticks))
        self.assertTrue(all(row['population']['actor_slots'] >= row['population']['minions_live'] for row in ticks))


class TestProcessTelemetry(unittest.TestCase):
    def test_joint_fit_recovers_elapsed_and_population_effects_not_marginal_slope(self):
        points = [(i/20,10+i//20+(i%11),3+.25*(i/20)+.7*(10+i//20+(i%11))) for i in range(500)]
        result = population_time_fit(points)
        self.assertTrue(result['identifiable'])
        self.assertAlmostEqual(result['elapsed_coefficient_per_minute'],.25)
        self.assertAlmostEqual(result['population_coefficient'],.7)
        self.assertAlmostEqual(result['intercept'],3)
        self.assertLess(result['rmse'],1e-10)
        flat = population_time_fit([(t,p,y-.25*t) for t,p,y in points])
        self.assertAlmostEqual(flat['elapsed_coefficient_per_minute'],0)
        self.assertFalse(population_time_fit([(i,2*i,3*i) for i in range(10)])['identifiable'])
        self.assertFalse(population_time_fit([(i,3,2*i) for i in range(10)])['identifiable'])

    def test_summarizer_keeps_process_resources_separate_and_ignores_legacy_sidecars(self):
        output = pp.new_output()
        for name,role,pid,rss in (('telemetry.jsonl','server',101,100),
                                  ('participant-telemetry.jsonl','participants',202,800)):
            (output/name).write_text(''.join(json.dumps({'wall_time':t,'cpu_s':t*(1 if role=='server' else 2),
                'rss':rss,'private_bytes':rss-10,'matches':[],'pid':pid,'role':role})+'\n' for t in (0,60)))
        (output/'server.log').write_text('')
        (output/('inputs-'+'a'*32+'.gc.jsonl')).write_text('{"not_a_journal":true}\n')
        summary = {'started_at':0,'started_monotonic_ns':0,
                   'server_process':{'isolated':True,'server_pid':101,'participant_pid':202}}
        summarize(output,summary)
        self.assertEqual(summary['peak_rss'],100)
        self.assertEqual(summary['process_telemetry']['server']['cpu_seconds'],60)
        self.assertEqual(summary['process_telemetry']['participants']['cpu_seconds'],120)
        self.assertEqual(summary['process_telemetry']['participants']['peak_rss'],800)
        summary['server_process']['participant_pid'] = 101
        with self.assertRaisesRegex(ValueError,'does not match'):
            summarize(output,summary)


if __name__ == '__main__':
    unittest.main()
