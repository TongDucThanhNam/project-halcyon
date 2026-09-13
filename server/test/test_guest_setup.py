"""Unit tests for guest_setup.py (LAN routing, firewall policies, mount state)."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.platform import guest_setup


class TestGuestSetup(unittest.TestCase):
    def test_mount_state(self):
        lines = [
            "/dev/block/sda1 /system/etc/hosts ext4 ro 0 0",
            "/data/local/tmp/halcyon-hosts-20260905 /system/etc/hosts none rw,bind 0 0",
            "/dev/block/sda2 /system/etc/security/cacerts ext4 ro 0 0",
        ]
        self.assertEqual(
            guest_setup.mount_state(lines, "/system/etc/hosts", "halcyon-hosts"),
            "ours"
        )
        self.assertEqual(
            guest_setup.mount_state(lines, "/system/etc/security/cacerts", "halcyon-cacerts"),
            "foreign"
        )
        self.assertEqual(
            guest_setup.mount_state(lines, "/unknown/target", "hint"),
            "missing"
        )

    def test_rule_present(self):
        mock_output = (
            "-P OUTPUT ACCEPT\n"
            "-A OUTPUT -m owner --uid-owner 10060 -m comment --comment halcyon-local-only -j REJECT\n"
            "-A OUTPUT -p tcp -m tcp --dport 80 -m comment --comment halcyon-local-route -j REDIRECT --to-ports 8080\n"
        )
        with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout=mock_output)):
            self.assertTrue(guest_setup.rule_present("emu", "iptables", [], ["halcyon-local-only"]))
            self.assertTrue(guest_setup.rule_present("emu", "iptables", [], ["halcyon-local-route", "--to-ports 8080"]))
            self.assertFalse(guest_setup.rule_present("emu", "iptables", [], ["nonexistent-tag"]))

    def test_ensure_firewall_local(self):
        commands_run = []
        def fake_su(serial, cmd, timeout=20):
            commands_run.append(cmd)
            # Pretend rules are not present initially
            return subprocess.CompletedProcess([], 0, stdout="")

        with mock.patch.object(guest_setup, "su", side_effect=fake_su):
            ok = guest_setup.ensure_firewall("emu", uid=10060, http=8080, https=8443, host="127.0.0.1")
            self.assertTrue(ok)
            joined = " ".join(commands_run)
            self.assertIn("halcyon-local-only", joined)
            self.assertIn("--to-ports 8080", joined)
            self.assertIn("--to-ports 8443", joined)
            self.assertNotIn("halcyon-target-host", joined)

    def test_ensure_firewall_lan(self):
        commands_run = []
        def fake_su(serial, cmd, timeout=20):
            commands_run.append(cmd)
            return subprocess.CompletedProcess([], 0, stdout="")

        with mock.patch.object(guest_setup, "su", side_effect=fake_su):
            ok = guest_setup.ensure_firewall("emu", uid=10060, http=8080, https=8443, host="192.168.1.50")
            self.assertTrue(ok)
            joined = " ".join(commands_run)
            self.assertIn("halcyon-target-host-192.168.1.50", joined)
            self.assertIn("192.168.1.50/32", joined)
            self.assertIn("ACCEPT", joined)
            self.assertIn("halcyon-local-only", joined)

    def test_ensure_firewall_lan_with_redirect(self):
        commands_run = []
        def fake_su(serial, cmd, timeout=20):
            commands_run.append(cmd)
            return subprocess.CompletedProcess([], 0, stdout="")

        with mock.patch.object(guest_setup, "su", side_effect=fake_su):
            ok = guest_setup.ensure_firewall("emu", uid=10060, http=8080, https=8443, host="192.168.1.50", redirect_lan=True)
            self.assertTrue(ok)
            joined = " ".join(commands_run)
            self.assertIn("halcyon-lan-route", joined)
            self.assertIn("DNAT", joined)
            self.assertIn("192.168.1.50:8080", joined)
            self.assertIn("192.168.1.50:8443", joined)

    def test_hosts_content_ok(self):
        with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="192.168.1.50 rpc.kindred-live.net")):
            self.assertTrue(guest_setup.hosts_content_ok("emu", host="192.168.1.50"))
            self.assertFalse(guest_setup.hosts_content_ok("emu", host="127.0.0.1"))

    def test_cli_parsing(self):
        with mock.patch.object(guest_setup, "preflight", return_value=True), \
             mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="uid=0(root)")), \
             mock.patch.object(guest_setup, "package_uid", return_value=10123), \
             mock.patch.object(guest_setup, "mounts", return_value=[]), \
             mock.patch.object(guest_setup, "ensure_hosts_source", return_value=True), \
             mock.patch.object(guest_setup, "ensure_cacerts_source", return_value=True), \
             mock.patch.object(guest_setup, "ensure_mount", return_value=True), \
             mock.patch.object(guest_setup, "ensure_firewall", return_value=True), \
             mock.patch.object(guest_setup, "verify_dns", return_value=True):
            rc = guest_setup.main(["--host", "192.168.1.77", "--serial", "emu-9999", "--redirect-lan"])
            self.assertEqual(rc, 0)

    def test_uid_discovery_requires_exact_package(self):
        for output, expected in (("package:com.superevilmegacorp.game uid:10123\n", 10123),
                                 ("package:com.superevilmegacorp.game.beta uid:10060\n", None)):
            with mock.patch.object(guest_setup, "run", return_value=subprocess.CompletedProcess([], 0, stdout=output)):
                if expected is None:
                    with self.assertRaises(ValueError):
                        guest_setup.package_uid("emu")
                else:
                    self.assertEqual(guest_setup.package_uid("emu"), expected)

    def test_first_hosts_creation_works_with_real_su_quoting(self):
        missing = subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        written = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(guest_setup, "run", side_effect=[missing, written]) as run:
            self.assertTrue(guest_setup.ensure_hosts_source("emu"))
            command = run.call_args.args[0][-1]
            self.assertIn('printf "%b"', command)
            self.assertIn('127.0.0.1 rpc.kindred-live.net', command)
            self.assertEqual(command.count("'"), 2)

    def test_localhost_line_does_not_hide_stale_lan_routing(self):
        stale = subprocess.CompletedProcess([], 0, stdout="127.0.0.1 localhost\n192.168.1.9 rpc.kindred-live.net\n")
        written = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(guest_setup, "run", side_effect=[stale, written]) as run:
            self.assertTrue(guest_setup.ensure_hosts_source("emu"))
            self.assertEqual(run.call_count, 2)

    def test_missing_root_does_not_modify_guest(self):
        with mock.patch.object(guest_setup, "preflight", return_value=True), \
             mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="uid=2000(shell)")), \
             mock.patch.object(guest_setup, "ensure_hosts_source") as hosts:
            self.assertEqual(guest_setup.main(["--serial", "emu"]), 2)
            hosts.assert_not_called()

    def test_old_uid_rule_does_not_hide_new_install(self):
        existing = "-A OUTPUT -m owner --uid-owner 10060 -m comment --comment halcyon-local-only -j REJECT\n"
        with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout=existing)) as su:
            self.assertTrue(guest_setup.ensure_firewall("emu", 10123, 8080, 8443))
            inserted = [call.args[1] for call in su.call_args_list if "-I OUTPUT" in call.args[1]]
            self.assertEqual(sum("--uid-owner 10123" in command for command in inserted), 2)

    def test_rule_markers_must_belong_to_one_rule(self):
        existing = "--comment halcyon-local-only --uid-owner 10060\n--comment other --uid-owner 10123\n"
        with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout=existing)):
            self.assertFalse(guest_setup.rule_present("emu", "iptables", [],
                             ["halcyon-local-only", "--uid-owner 10123"]))

    def test_new_ca_replaces_stale_guest_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "platform_cert.pem"
            certificate.write_text("new local CA\n", encoding="ascii")
            def guest(serial, command, timeout=20):
                return subprocess.CompletedProcess([], 0, stdout="old CA" if command.startswith("cat ") else "present")
            with mock.patch.object(guest_setup, "su", side_effect=guest) as su, \
                 mock.patch.object(guest_setup, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")) as adb:
                self.assertTrue(guest_setup.ensure_cacerts_source("emu", str(certificate)))
                adb.assert_called_once()
                self.assertIn("push", adb.call_args.args[0])
                self.assertTrue(any("chmod 0644" in call.args[1] for call in su.call_args_list))

    def test_first_certificate_generation_uses_no_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            def generate():
                (folder / "platform_cert.pem").write_text("generated CA\n", encoding="ascii")
            with mock.patch.object(guest_setup, "stack_dir", return_value=folder), \
                 mock.patch("server.platform.mkcert.main", side_effect=generate) as mkcert, \
                 mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="present")), \
                 mock.patch.object(guest_setup, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")):
                self.assertTrue(guest_setup.ensure_cacerts_source("emu"))
                mkcert.assert_called_once_with()

    def test_stale_mounted_ca_does_not_pass_by_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "platform_cert.pem"
            certificate.write_text("new CA\n", encoding="ascii")
            with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="old CA\n")):
                self.assertFalse(guest_setup.cacerts_content_ok("emu", str(certificate)))
            with mock.patch.object(guest_setup, "su", return_value=subprocess.CompletedProcess([], 0, stdout="new CA\n")):
                self.assertTrue(guest_setup.cacerts_content_ok("emu", str(certificate)))


if __name__ == "__main__":
    unittest.main()
