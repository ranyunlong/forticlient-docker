import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class VPNSessionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.session = importlib.import_module("vpn_session")
        except ImportError:
            self.fail("The container startup parameter handler is not implemented")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {"host": "vpn.example.test", "username": "test-user", "password": "test-password"}

    def fake_cli(self, body):
        script = self.root / "forticlient"
        script.write_text("#!/usr/bin/env python3\nimport sys\n" + body)
        script.chmod(0o755)
        self.environment = patch.dict(os.environ, {"PATH": str(self.root) + os.pathsep + os.environ["PATH"]})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_config_defaults_to_443_and_rejects_line_injection(self):
        path = self.root / "vpn.json"
        path.write_text(json.dumps(self.config))
        self.assertEqual(self.session.load_config(path)["port"], 443)
        self.config["host"] = "vpn.example.test\nattacker"
        path.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError):
            self.session.load_config(path)

    def test_config_rejects_boolean_port(self):
        path = self.root / "vpn.json"
        path.write_text(json.dumps({**self.config, "port": True}))
        with self.assertRaises(ValueError):
            self.session.load_config(path)

    def test_config_applies_gateway_without_saving_credentials(self):
        self.fake_cli("""assert sys.argv[1:] == ['vpn', 'edit', 'container-vpn']
assert sys.stdin.read() == 'vpn.example.test\\n443\\n1\\n3\\n'
print('DONE.')
""")
        self.session.configure({**self.config, "port": 443})

    def test_connect_answers_password_and_fortitoken_without_printing_them(self):
        self.fake_cli("""assert sys.argv[1:] == ['vpn', 'connect', 'container-vpn', '-u', 'test-user', '-p']
print('Password:', end='', flush=True)
assert input() == 'test-password'
print('A FortiToken code is required.\\nFortiToken:', end='', flush=True)
assert input() == '987654'
print('Status: Connected')
""")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.session.connect(self.config, "987654", timeout=3)
        self.assertNotIn("test-password", output.getvalue())
        self.assertNotIn("987654", output.getvalue())

    def test_repeated_challenge_does_not_reuse_token(self):
        self.fake_cli("""print('Password:', end='', flush=True)
input()
print('FortiToken:', end='', flush=True)
input()
print('FortiToken:', end='', flush=True)
input()
""")
        with self.assertRaisesRegex(RuntimeError, "令牌|token"):
            self.session.connect(self.config, "987654", timeout=3)

    def test_authentication_failure_redacts_password_and_token(self):
        self.fake_cli("""print('Password:', end='', flush=True)
input()
print('Error: test-password 987654', flush=True)
sys.exit(1)
""")
        with self.assertRaises(RuntimeError) as error:
            self.session.connect(self.config, "987654", timeout=3)
        self.assertNotIn("test-password", str(error.exception))
        self.assertNotIn("987654", str(error.exception))

    def test_empty_stdin_does_not_reuse_environment_token(self):
        with patch.dict(os.environ, {"FORTITOKEN": "old-token"}), patch("sys.stdin", io.StringIO("")):
            with self.assertRaises(ValueError):
                self.session.read_token()


if __name__ == "__main__":
    unittest.main()
