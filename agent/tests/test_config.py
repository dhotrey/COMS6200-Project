"""Offline checks for agent environment defaults and sudo skip."""
import os
import unittest
from unittest.mock import patch


class ConfigTests(unittest.TestCase):
    def test_import_leaves_onos_credentials_set(self):
        from agent import config
        self.assertTrue(os.environ.get("ONOS_USER", "").strip())
        self.assertTrue("ONOS_PASSWORD" in os.environ)
        self.assertTrue(config.REPO_ROOT.is_dir())

    def test_ensure_privileges_skips_under_pytest(self):
        from agent import config
        with patch.object(os, "geteuid", return_value=1000), patch.object(os, "execvp") as execvp:
            config.ensure_mininet_privileges()
        execvp.assert_not_called()

    def test_sudo_reexec_keeps_topology_selection(self):
        from agent import config
        env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_CURRENT_TEST", "COMS6200_AGENT_NO_SUDO")}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(os, "geteuid", return_value=1000, create=True), \
                patch.object(os, "execvp") as execvp, \
                patch("builtins.print"):
            config.ensure_mininet_privileges()
        preserve = execvp.call_args.args[1][1]
        self.assertTrue(preserve.startswith("--preserve-env="), preserve)
        self.assertIn("COMS6200_TOPOLOGY", preserve.split("=", 1)[1].split(","))
