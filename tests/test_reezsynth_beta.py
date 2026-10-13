"""EbSynth Beta project interchange and isolated GUI controls."""

import os
import struct
import shutil
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from reezsynth_beta_project import Interval, Project, from_bytes, read, to_bytes
from reezsynth_beta_controls import BetaProjectTab, rebase_paths


def sample_project():
    return Project(
        video=r"video\frame[##].png", mask=r"masks\mask[##].png",
        keys=r"keys\style[##].png", mask_enabled=True,
        key_weight=1.0, video_weight=6.0, mask_weight=2.0,
        mapping=2.0, deflicker=0.5, diversity=3500.0,
        intervals=(Interval(11, True, True, 11, 11,
                            r"outputs\key11\[##].png"),),
        detail=1, gpu=True, fps=24.0,
    )


@contextmanager
def test_directory():
    root = Path(__file__).resolve().parents[1] / "diagnostic_outputs"
    root.mkdir(exist_ok=True)
    folder = root / ("beta-test-" + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


class BetaProjectTests(unittest.TestCase):
    def test_known_layout_and_truncation(self):
        project = sample_project()
        strings = (project.video, project.mask, project.keys)
        fixture = bytearray(b"EBS05\0")
        for value in strings:
            data = value.encode("ascii")
            fixture += struct.pack("<i", len(data)) + data
        fixture += struct.pack("<B6fi", 1, 1, 6, 2, 2, 0.5, 3500, 1)
        fixture += struct.pack("<iBBii", 11, 1, 1, 11, 11)
        output = project.intervals[0].output.encode("ascii")
        fixture += struct.pack("<i", len(output)) + output
        fixture += b"V02\0" + struct.pack("<iBfi", 1, 1, 24, 704)
        self.assertEqual(from_bytes(bytes(fixture)), project)
        self.assertEqual(to_bytes(project), bytes(fixture))
        with self.assertRaises(ValueError):
            from_bytes(bytes(fixture[:-1]))

    def test_decimal_weight_is_encoded_as_beta_float32(self):
        project = replace(sample_project(), video_weight=0.1)
        decoded = from_bytes(to_bytes(project))
        self.assertAlmostEqual(decoded.video_weight, 0.1, places=6)
        with self.assertRaises(ValueError):
            to_bytes(replace(project, video_weight=1e39))

    def test_save_copy_preserves_original_and_rebases_paths(self):
        with test_directory() as root:
            first = root / "inputs" / "original.ebs"
            second = root / "saved" / "copy.ebs"
            first.parent.mkdir()
            second.parent.mkdir()
            original = to_bytes(sample_project())
            first.write_bytes(original)
            app = self._application()
            tab = BetaProjectTab()
            tab.load_project(first)
            tab.fields["video_weight"].setText("7")
            tab.save_project_copy(second)
            self.assertEqual(first.read_bytes(), original)
            copied = read(second)
            self.assertEqual(copied.video_weight, 7)
            self.assertEqual(copied.video, r"..\inputs\video\frame[##].png")
            self.assertEqual(copied.intervals[0].output,
                             r"..\inputs\outputs\key11\[##].png")
            with self.assertRaises(FileExistsError):
                tab.save_project_copy(second)
            tab.close()
            self.assertIsNotNone(app)

    def test_rebase_keeps_absolute_paths(self):
        with test_directory() as root:
            project = sample_project()
            absolute = str((root / "video" / "frame[##].png").resolve())
            project = Project(absolute, project.mask, project.keys,
                              project.mask_enabled, project.key_weight,
                              project.video_weight, project.mask_weight,
                              project.mapping, project.deflicker,
                              project.diversity, project.intervals,
                              project.detail, project.gpu, project.fps)
            moved = rebase_paths(project, root, root / "other")
            self.assertEqual(moved.video, absolute)

    @staticmethod
    def _application():
        from PySide6.QtWidgets import QApplication
        return QApplication.instance() or QApplication([])


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    unittest.main()
