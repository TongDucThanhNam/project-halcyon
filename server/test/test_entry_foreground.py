"""A native sign-in cancellation must not restart the game underneath it."""
import unittest
from unittest.mock import Mock, patch
from Tools import scenario_client as sc


class EntryForegroundTests(unittest.TestCase):
    def test_native_back_returns_to_game_without_coordinate_guess_or_relaunch(self):
        driver = object.__new__(sc.ClientDriver)
        driver.adb = Mock()
        driver._foreground_package = Mock(side_effect=[
            'com.google.android.gms', sc.ANDROID_PACKAGE,
            sc.ANDROID_PACKAGE, sc.ANDROID_PACKAGE])
        driver._screen_still = Mock(side_effect=AssertionError('dialog is not a renderer test'))
        driver.gesture = Mock(side_effect=lambda kind, **record: record)
        with patch.object(sc.time, 'sleep'):
            result = driver._ensure_game_foreground('entry')
        driver.adb.back.assert_called_once_with()
        driver.adb.tap.assert_not_called()
        driver.adb.shell.assert_not_called()
        self.assertTrue(result['recovered'])
        self.assertEqual(result['cancelled_gms_signin'], 1)

    def test_game_foreground_never_receives_back(self):
        driver = object.__new__(sc.ClientDriver)
        driver.adb = Mock()
        driver._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.assertIsNone(driver._ensure_game_foreground('entry'))
        driver.adb.back.assert_not_called()

    def test_recovery_rechecks_foreign_app_instead_of_repeating_gms_back(self):
        driver = object.__new__(sc.ClientDriver)
        driver.adb = Mock()
        driver._foreground_package = Mock(side_effect=[
            'com.google.android.gms', 'com.android.chrome',
            'com.android.chrome', 'com.android.chrome',
            sc.ANDROID_PACKAGE, sc.ANDROID_PACKAGE])
        driver.gesture = Mock(side_effect=lambda kind, **record: record)
        with patch.object(sc.time, 'sleep'):
            result = driver._ensure_game_foreground('entry')
        driver.adb.back.assert_called_once_with()
        driver.adb.shell.assert_any_call('am force-stop com.android.chrome')
        self.assertTrue(result['recovered'])


if __name__ == '__main__':
    unittest.main()
