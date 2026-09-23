from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def requirements(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError("Requirements include cycle")
    seen.add(path)
    output = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-r "):
            output.extend(requirements(path.parent / line[3:], seen.copy()))
        elif line and not line.startswith("#"):
            output.append(line)
    return output


class DependencyTests(unittest.TestCase):
    def test_module_owns_ocr_dependencies_and_root_aggregates(self):
        runtime = requirements(ROOT / "requirements.txt")
        self.assertIn("pypdf==6.10.2", runtime)
        self.assertIn("easyocr==1.7.2", runtime)
        self.assertIn("transformers==5.10.0", runtime)
        self.assertIn("safetensors==0.8.0", runtime)
        self.assertIn("torch==2.8.0", runtime)
        self.assertNotIn("PyInstaller==6.22.3", runtime)
        self.assertEqual(len(runtime), len(set(runtime)))
        self.assertEqual(
            (ROOT / "requirements.txt").read_text(encoding="utf-8").strip(),
            "-r modules/ocr/requirements.txt",
        )

    def test_lightweight_and_build_requirements_are_separate(self):
        self.assertEqual(requirements(ROOT / "modules/ocr/requirements-text.txt"), ["pypdf==6.10.2"])
        build = requirements(ROOT / "packaging/requirements.txt")
        self.assertIn("PyInstaller==6.22.3", build)
        self.assertIn("easyocr==1.7.2", build)
        self.assertFalse((ROOT / "requirements-build.txt").exists())
        self.assertFalse((ROOT / "requirements-ocr.txt").exists())

    def test_module_prep_is_in_module_not_runtime_import(self):
        self.assertTrue((ROOT / "modules/ocr/prepare.py").is_file())
        self.assertNotIn("prepare", (ROOT / "modules/ocr/engine.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
