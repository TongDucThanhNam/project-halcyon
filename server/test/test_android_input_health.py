import unittest
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


if __name__=='__main__':
    unittest.main()
