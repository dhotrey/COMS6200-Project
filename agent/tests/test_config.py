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
