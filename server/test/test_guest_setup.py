"""Unit tests for guest_setup.py (LAN routing, firewall policies, mount state)."""
import subprocess
import unittest
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
             mock.patch.object(guest_setup, "mounts", return_value=[]), \
             mock.patch.object(guest_setup, "ensure_hosts_source", return_value=True), \
             mock.patch.object(guest_setup, "ensure_cacerts_source", return_value=True), \
             mock.patch.object(guest_setup, "ensure_mount", return_value=True), \
             mock.patch.object(guest_setup, "ensure_firewall", return_value=True), \
             mock.patch.object(guest_setup, "verify_dns", return_value=True):
            rc = guest_setup.main(["--host", "192.168.1.77", "--serial", "emu-9999", "--redirect-lan"])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
