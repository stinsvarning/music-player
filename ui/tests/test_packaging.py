import unittest
from pathlib import Path
from unittest.mock import patch

from music_player.app import engine_entry
from music_player.theme import FALLBACK, load_active_palette


ROOT = Path(__file__).resolve().parents[2]


class PackagingPathsTests(unittest.TestCase):
    def test_repo_launch_files_have_no_machine_home(self):
        files = [
            ROOT / "packaging" / "music-player.desktop",
            ROOT / "packaging" / "install.sh",
            ROOT / "packaging" / "uninstall.sh",
            ROOT / "packaging" / "install-service.sh",
            ROOT / "packaging" / "systemd" / "music-player-engine.service.in",
            ROOT / "packaging" / "hypr-bindings.lua",
            ROOT / "packaging" / "aur" / "PKGBUILD",
            ROOT / "packaging" / "llurd.music" / "BarWidget.qml",
            ROOT / "music-player",
            Path(__import__("music_player.app", fromlist=["engine_entry"]).__file__),
        ]
        for path in files:
            text = path.read_text()
            self.assertNotIn("/home/llurd", text, msg=str(path))

    def test_desktop_template_execs_path_command(self):
        text = (ROOT / "packaging" / "music-player.desktop").read_text()
        self.assertIn("Exec=music-player", text)
        self.assertIn("Name=Music", text)
        self.assertIn("Version=0.2.0", text)

    def test_release_files_exist(self):
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "0.2.0")
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())
        uninstall = (ROOT / "packaging" / "uninstall.sh").read_text()
        self.assertIn("--purge-config", uninstall)
        self.assertIn("--purge-extras", uninstall)
        install = (ROOT / "packaging" / "install.sh").read_text()
        self.assertIn("uninstall.sh", install)
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("<this-repo>", readme)
        self.assertNotIn("After you publish", readme)
        self.assertNotIn("cliamp", readme.lower())
        self.assertIn("github.com/stinsvarning/music-player", readme)
        pkgbuild = (ROOT / "packaging" / "aur" / "PKGBUILD").read_text()
        self.assertIn("pkgname=music-player-git", pkgbuild)
        self.assertIn("github.com/stinsvarning/music-player", pkgbuild)
        self.assertFalse((ROOT / "docs/superpowers").exists())

    def test_engine_entry_is_beside_the_ui_tree(self):
        entry = Path(engine_entry())
        self.assertEqual(entry.name, "index.js")
        self.assertEqual(entry.parent.name, "src")
        self.assertEqual(entry.parent.parent.name, "engine")
        self.assertTrue(entry.is_file())


class ThemeFallbackTests(unittest.TestCase):
    def test_missing_omarchy_theme_uses_fallback(self):
        missing = Path("/no/such/omarchy/current/theme/colors.toml")
        with patch("music_player.theme.omarchy_colors_paths", return_value=[missing]):
            palette = load_active_palette()
        self.assertEqual(palette, FALLBACK)


class ServiceUnitTests(unittest.TestCase):
    def test_unit_template_restarts_only_on_failure(self):
        text = (ROOT / "packaging" / "systemd" / "music-player-engine.service.in").read_text()
        self.assertIn("ExecStart=@NODE@ @ENGINE@", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("WantedBy=graphical-session.target", text)

    def test_install_service_renders_a_unit(self):
        import os
        import subprocess
        import tempfile

        script = ROOT / "packaging" / "install-service.sh"
        self.assertTrue(os.access(script, os.X_OK))
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "bin"
            fake.mkdir()
            (fake / "systemctl").write_text("#!/bin/sh\necho \"$@\" >> \"$SYSTEMCTL_LOG\"\n")
            (fake / "systemctl").chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                "XDG_CONFIG_HOME": str(Path(tmp) / "cfg"),
                "SYSTEMCTL_LOG": str(Path(tmp) / "log"),
            }
            out = subprocess.run([str(script), "--repo", "--enable"], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            unit = (Path(tmp) / "cfg" / "systemd" / "user" / "music-player-engine.service").read_text()
            self.assertNotIn("@NODE@", unit)
            self.assertIn(str(ROOT / "engine" / "src" / "index.js"), unit)
            log = (Path(tmp) / "log").read_text()
            self.assertIn("--user daemon-reload", log)
            self.assertIn("--user enable music-player-engine.service", log)
            out = subprocess.run([str(script), "--remove"], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertFalse((Path(tmp) / "cfg" / "systemd" / "user" / "music-player-engine.service").exists())
