import unittest

from Tools.android_input_health import native_input_lifecycle


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


if __name__=='__main__':
    unittest.main()
