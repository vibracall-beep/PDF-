import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import startup_observation as probe


class StartupObservationTests(unittest.TestCase):
    def test_exact_sources_are_required_and_original_bytes_unchanged(self):
        for name, expected in probe.SOURCE_HASHES.items():
            original = (probe.ROOT / "Sources/PDF" / name).read_bytes()
            self.assertEqual(probe.digest(original), expected)
            instrumented = probe.instrument(name, original)
            self.assertNotEqual(original.decode(), instrumented)
            self.assertEqual((probe.ROOT / "Sources/PDF" / name).read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "source hash changed"):
                probe.instrument(name, original + b"\n")

    def test_ambiguous_or_missing_anchor_is_rejected(self):
        for body in ("prefix", "target target"):
            with self.assertRaises(ValueError):
                probe.replace(body, "target", "replacement")
        self.assertEqual(probe.replace("a target z", "target", "new"), "a new z")

    def test_stage_preserves_installer_and_records_exact_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repository = root / "repository"; repository.mkdir()
            def git(*args):
                return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, timeout=15)
            git("init", "-q")
            git("config", "user.name", "Diagnostic test"); git("config", "user.email", "test@invalid.local")
            for name in probe.SOURCE_HASHES:
                target = repository / "Sources/PDF" / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((probe.ROOT / "Sources/PDF" / name).read_bytes())
            installer = repository / "scripts/install-mac.sh"; installer.parent.mkdir()
            original_installer = (probe.ROOT / "scripts/install-mac.sh").read_bytes()
            installer.write_bytes(original_installer); installer.chmod(0o700)
            git("add", "."); git("commit", "-qm", "Fixture")
            (repository / "untracked-secret.txt").write_text("not part of source")
            output = root / "diagnostic"
            with contextlib.redirect_stdout(io.StringIO()):
                probe.prepare(repository, output)
            self.assertFalse((output / "source/untracked-secret.txt").exists())
            self.assertEqual((output / "source/scripts/install-mac.sh").read_bytes(), original_installer)
            self.assertTrue((output / "source/scripts/install-mac.sh").stat().st_mode & 0o100)
            manifest = json.loads((output / "evidence/instrumentation.json").read_text())
            self.assertEqual(len(manifest["changes"]), 3)
            for change in manifest["changes"]:
                self.assertEqual(probe.digest((repository / change["path"]).read_bytes()), change["before_sha256"])
                self.assertEqual(probe.digest((output / "source" / change["path"]).read_bytes()), change["after_sha256"])
                self.assertTrue((output / "evidence" / (Path(change["path"]).name + ".patch")).read_text().startswith("--- original/"))
            with self.assertRaises(FileExistsError):
                probe.prepare(repository, output)

    def test_launch_completion_alone_never_means_a_window(self):
        report = probe.summarize("PDF preview startup: application did finish launching; windows=0; visible=0\n")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["window_observation"], "none")
        self.assertFalse(report["main_queue_responsive"])

    def test_responsive_application_can_have_no_attached_scene(self):
        log = "\n".join("PDF preview startup: " + phase + "; windows=0; visible=0" for phase in (
            "application did finish launching", "post-launch main queue turn", "post-launch two-second observation"))
        report = probe.summarize(log)
        self.assertEqual(report["status"], "windowgroup_not_attached")
        self.assertEqual(report["window_observation"], "none")
        self.assertTrue(report["main_queue_responsive"])

    def test_visible_window_still_requires_real_scene_and_queue(self):
        phases = ["entrypoint begin; acquire bundle lease", "PDFApp body evaluated", "application did finish launching",
                  "post-launch main queue turn", "post-launch two-second observation", "WindowGroup content builder evaluated",
                  "diagnostic WindowGroup attached; capture sequence paused"]
        log = "\n".join("PDF preview startup: " + phase + "; windows=1; visible=1" for phase in phases)
        report = probe.summarize(log)
        self.assertEqual(report["status"], "window_attached")
        self.assertEqual(report["product_approval"], "not_evaluated")
        self.assertNotEqual(probe.summarize(log.replace(phases[-1], "unrelated"))["status"], "window_attached")
        hidden = probe.summarize(log.replace("visible=1", "visible=0"))
        self.assertEqual(hidden["status"], "attached_without_observed_visibility")
        self.assertEqual(hidden["window_observation"], "present_hidden")
        self.assertTrue(hidden["markers"]["attached"])
        self.assertEqual(probe.summarize("")["window_observation"], "unknown")


if __name__ == "__main__":
    unittest.main()
