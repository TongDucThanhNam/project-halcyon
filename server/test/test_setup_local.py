"""Fresh configuration must work without an operator's TEMP directory or token."""
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SetupLocalTests(unittest.TestCase):
    def test_check_requires_every_example_method_but_not_metadata_and_never_repairs(self):
        from Tools.setup_local import check_answer_methods
        config = json.loads((ROOT/'Config/answers.example.json').read_text(encoding='utf-8'))
        methods = {k: v for k, v in config.items() if not k.startswith('_')}
        check_answer_methods(methods)
        for method in methods:
            partial = dict(methods)
            del partial[method]
            before = json.dumps(partial, sort_keys=True)
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, method):
                check_answer_methods(partial)
            self.assertEqual(json.dumps(partial, sort_keys=True), before)

    def test_check_reports_missing_join_lobby_without_editing_runtime_answers(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'Local/evidence', prefix='setup-check-') as temporary:
            folder = Path(temporary)
            self.assertEqual(self.initialize(folder).returncode, 0)
            target = folder/'runtime/halcyon_stack/answers.json'
            config = json.loads(target.read_text(encoding='utf-8'))
            del config['joinLobby']
            target.write_text(json.dumps(config), encoding='utf-8')
            before = target.read_bytes()
            result = subprocess.run([sys.executable, '-B', str(ROOT/'Tools/setup_local.py'), '--check'],
                env=dict(os.environ, HALCYON_STACK_DIR=str(target.parent)), cwd=ROOT,
                capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('MISSING/INVALID platform configuration: answers.json missing method rows', result.stdout)
            self.assertIn('joinLobby', result.stdout)
            self.assertEqual(target.read_bytes(), before)

    def initialize(self, directory):
        env = dict(os.environ, HALCYON_LOCAL_ROOT=str(directory),
                   HALCYON_STACK_DIR=str(directory / "runtime/halcyon_stack"))
        return subprocess.run([sys.executable, "-B", str(ROOT / "Tools/setup_local.py"), "--init"],
                              env=env, cwd=directory, capture_output=True, text=True, timeout=30)

    def test_fresh_init_generates_usable_pair_and_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = self.initialize(folder)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            runtime = folder / "runtime/halcyon_stack"
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(runtime / "platform_cert.pem", runtime / "platform_key.pem")
            config_file = runtime / "answers.json"
            config = json.loads(config_file.read_text(encoding="utf-8"))
            from server.platform.local_stack import _token_player_id
            token = config["startSessionForPlayer"]["returnValue"]["sessionToken"]
            self.assertTrue(_token_player_id(token))
            self.assertNotIn("__HALCYON_", token)
            config["_gw_port"] = 7189
            config_file.write_text(json.dumps(config), encoding="utf-8")
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.iterdir()}
            second = self.initialize(folder)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.iterdir()})

    def test_partial_key_pair_fails_without_replacing_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            runtime = folder / "runtime/halcyon_stack"
            runtime.mkdir(parents=True)
            key = runtime / "platform_key.pem"
            key.write_bytes(b"private key fixture to preserve")
            result = self.initialize(folder)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incomplete certificate/key pair", result.stderr)
            self.assertEqual(key.read_bytes(), b"private key fixture to preserve")
            self.assertFalse((runtime / "answers.json").exists())


if __name__ == "__main__":
    unittest.main()
