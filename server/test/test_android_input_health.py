import unittest
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from Tools.android_input_health import native_input_lifecycle
from Tools import android_input_health as health


def row(at, pid, marker):
    return f' {at:.3f} {pid} 12 D NUO : logFunctionName(RenderEvent - {marker}): NuoView$Renderer::executeState:718'


class NativeInputLifecycleTests(unittest.TestCase):
    def test_foreground_does_not_override_unfinished_or_suspended_native_state(self):
        for final in ('Resume - Pre', 'Suspend - Pre', 'Suspend - Post'):
            log = row(1,100,'Resume - Post')+'\n'+row(2,100,final)
            self.assertFalse(native_input_lifecycle(log,100)['ready'])

    def test_other_process_old_resume_and_missing_logs_are_not_ready(self):
        self.assertFalse(native_input_lifecycle(row(5,101,'Resume - Post'),100)['ready'])
        self.assertFalse(native_input_lifecycle(row(5,100,'Resume - Post'),100,after_guest_wall=6)['ready'])
        self.assertFalse(native_input_lifecycle('',100)['ready'])

    def test_new_completed_resume_qualifies_only_the_current_process(self):
        log='\n'.join([row(5,100,'Resume - Pre'),row(6,100,'Resume - Post'),row(7,101,'Suspend - Post')])
        state=native_input_lifecycle(log,100,after_guest_wall=5)
        self.assertTrue(state['ready'])
        self.assertEqual(state['latest']['guest_wall'],6)


class LaunchReadinessTests(unittest.TestCase):
    activities = ('* Hist #0: ActivityRecord{x com.superevilmegacorp.game/'
                  'com.superevilmegacorp.nuogameentry.NuoActivityGame t1}\n'
                  ' state=RESUMED\n app=ProcessRecord{x 100:com.superevilmegacorp.game/u0a70}')

    def test_pid_resumed_and_initialized_resume_are_all_required(self):
        log = row(6, 100, 'Resume - Post')
        self.assertTrue(health.launch_readiness('100', self.activities, log, after_guest_wall=5)['ready'])
        cases = [('absent', '', self.activities, log), ('ambiguous', '100 101', self.activities, log),
                 ('paused', '100', self.activities.replace('RESUMED', 'PAUSED'), log),
                 ('wrong_pid', '101', self.activities, log),
                 ('init_not_completion', '100', self.activities, '6.0 100 1 D NUO : logFunctionName(init)'),
                 ('wrong_activity_header', '100', self.activities.replace('NuoActivityGame', 'OtherActivity') +
                  '\n mResumedActivity: com.superevilmegacorp.game/com.superevilmegacorp.nuogameentry.NuoActivityGame', log),
                 ('reinitialized_after_resume', '100', self.activities, log +
                  '\n 7.0 100 1 D NUO : logFunctionName(init): NuoView$Renderer::onSurfaceChanged:795'),
                 ('suspended', '100', self.activities, log+'\n'+row(7, 100, 'Suspend - Post'))]
        for name, pid, activities, text in cases:
            with self.subTest(name=name):
                self.assertFalse(health.launch_readiness(pid, activities, text, after_guest_wall=5)['ready'])

    def test_three_stable_samples_at_least_one_second_apart(self):
        adb, clock, observations = Mock(), [0.0], []
        def shell(command):
            if command.startswith('pidof'): return '100'
            if command.startswith('dumpsys'): return self.activities
            return row(6, 100, 'Resume - Post')
        adb.shell.side_effect = shell
        with patch.object(health.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(health.time, 'sleep', side_effect=lambda gap: clock.__setitem__(0, clock[0]+gap)):
            result = health.wait_launch_ready(adb, after_guest_wall=5, record=observations.append)
        self.assertTrue(result['ready'])
        self.assertEqual([r['monotonic'] for r in observations], [0, 1, 2])

    def test_pid_changes_reset_stability_and_never_attach(self):
        adb, clock = Mock(), [0.0]
        def shell(command):
            pid = 100 + int(clock[0])
            if command.startswith('pidof'): return str(pid)
            if command.startswith('dumpsys'): return self.activities.replace('100:', str(pid)+':')
            return row(6, pid, 'Resume - Post')
        adb.shell.side_effect = shell
        with patch.object(health.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(health.time, 'sleep', side_effect=lambda gap: clock.__setitem__(0, clock[0]+gap)):
            self.assertFalse(health.wait_launch_ready(adb, after_guest_wall=5, timeout=4)['ready'])


class OwnedWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.exe = Path(self.temp)/'dnplayer.exe'
        self.exe.touch()
        self.user, self.kernel = Mock(), Mock()
        self.user.EnumWindows.side_effect = lambda visit, _: visit(10, 0)
        self.user.GetClassNameW.side_effect = lambda hwnd, buf, count: setattr(buf, 'value', 'LDPlayerMainFrame' if hwnd == 10 else 'OtherApp') or 1
        def pid(hwnd, target):
            if target is not None:
                ctypes.cast(target, ctypes.POINTER(wintypes.DWORD))[0] = 100 if hwnd == 10 else 200
            return 1
        self.user.GetWindowThreadProcessId.side_effect = pid
        self.user.GetForegroundWindow.return_value = 20
        self.user.IsIconic.return_value = False
        self.user.IsWindow.return_value = True
        self.kernel.OpenProcess.side_effect = lambda access, inherit, pid: pid
        self.kernel.QueryFullProcessImageNameW.side_effect = lambda handle, flags, buf, size: setattr(buf, 'value', str(self.exe) if handle == 100 else 'other.exe') or 1
        self.enterContext(patch.object(ctypes, 'WinDLL', side_effect=lambda name, **kw: self.user if name == 'user32' else self.kernel))
        for name in ('SetForegroundWindow', 'BringWindowToTop', 'AttachThreadInput', 'SetFocus', 'MoveWindow', 'SetWindowPos'):
            getattr(self.user, name).side_effect = AssertionError('forbidden activation/movement API')
        self.addCleanup(self.assert_no_activation)

    def assert_no_activation(self):
        for name in ('SetForegroundWindow', 'BringWindowToTop', 'AttachThreadInput', 'SetFocus', 'MoveWindow', 'SetWindowPos'):
            getattr(self.user, name).assert_not_called()

    def test_other_app_or_peer_foreground_is_information_only(self):
        for foreground in (20, 30):
            self.user.GetForegroundWindow.return_value = foreground
            state = health.qualify_owned_ldplayer(self.exe, process_id=100)
            self.assertEqual(state['after_foreground']['hwnd'], foreground)
            self.assertEqual(state['after_foreground']['pid'], 200)
            health.require_owned_window(state)
        self.user.ShowWindow.assert_not_called()

    def test_minimized_restore_is_once_nonactivating_and_rechecked(self):
        self.user.IsIconic.side_effect = [True, False]
        self.assertTrue(health.qualify_owned_ldplayer(self.exe, process_id=100)['restore_attempted'])
        self.user.ShowWindow.assert_called_once_with(10, 4)

    def test_unrestorable_or_changed_window_is_not_qualified(self):
        self.user.IsIconic.return_value = True
        with self.assertRaisesRegex(ValueError, 'minimized'):
            health.qualify_owned_ldplayer(self.exe, process_id=100)
        self.user.ShowWindow.assert_called_once_with(10, 4)
        self.user.ShowWindow.reset_mock()
        with self.assertRaisesRegex(ValueError, 'minimized'):
            health.require_owned_window({'executable': self.exe, 'pid': 100, 'hwnd': 10})
        self.user.ShowWindow.assert_not_called()
        self.user.IsIconic.return_value = False
        with self.assertRaisesRegex(ValueError, 'window changed'):
            health.require_owned_window({'executable': self.exe, 'pid': 100, 'hwnd': 11})

    def test_wrong_pid_path_or_missing_window_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'absent or ambiguous'):
            health.qualify_owned_ldplayer(self.exe, process_id=101)
        other = Path(self.temp)/'other.exe'
        other.touch()
        with self.assertRaisesRegex(RuntimeError, 'absent or ambiguous'):
            health.qualify_owned_ldplayer(other, process_id=100)
        self.user.IsWindow.return_value = False
        with self.assertRaisesRegex(ValueError, 'absent/changed'):
            health.qualify_owned_ldplayer(self.exe, process_id=100)
        self.user.ShowWindow.assert_not_called()


class FrameworkReadinessTests(unittest.TestCase):
    def run_wait(self, signal, boot=lambda elapsed: '1', timeout=120):
        clock, rows, adb = [0.0], [], Mock()
        def shell(command, **kwargs):
            return boot(clock[0]) if command.startswith('getprop') else signal(clock[0])
        adb.shell.side_effect = shell
        with patch.object(health.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(health.time, 'sleep', side_effect=lambda gap: clock.__setitem__(0, clock[0]+gap)):
            result = health.wait_framework_ready(adb, timeout=timeout, record=rows.append)
        self.assertTrue(all('am start' not in call.args[0] for call in adb.shell.call_args_list))
        return result, clock[0]

    def test_old_records_are_retained_and_full_quiet_interval_required(self):
        result, elapsed = self.run_wait(lambda _: '1.0 ActivityManager: ANR in historical')
        self.assertTrue(result['ready'])
        self.assertEqual(elapsed, 65)
        self.assertEqual(result['observations'][0]['new_signals'], ['1.0 ActivityManager: ANR in historical'])

    def test_new_anr_or_force_stop_resets_quiet_window(self):
        for marker in ('ANR in', 'Force stopping'):
            result, elapsed = self.run_wait(lambda t: '' if t < 40 else f'40.0 {marker} owned')
            self.assertTrue(result['ready'])
            self.assertEqual(elapsed, 105)

    def test_boot_not_complete_and_continuous_anrs_expire_with_evidence(self):
        for signal, boot in ((lambda t: f'{t} ANR in system', lambda t: '1'),
                             (lambda t: '', lambda t: '0')):
            result, elapsed = self.run_wait(signal, boot, timeout=60)
            self.assertFalse(result['ready'])
            self.assertEqual(elapsed, 60)
            self.assertEqual(result['bound_s'], 60)
            self.assertTrue(result['observations'])


if __name__=='__main__':
    unittest.main()
