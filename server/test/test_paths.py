"""Portable private data selection must not accidentally use another corpus."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server import paths


class TestPrivateDataPaths(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="halcyon-paths-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.project = self.base / "checkout with spaces"
        self.project.mkdir()
        self.legacy_vg = self.base / "legacy originals"
        self.legacy_temp = self.base / "legacy temp"
        for target, value in (("_PROJECT_ROOT", self.project),
                              ("_LEGACY_VAINGLORY_ROOT", self.legacy_vg)):
            replacement = patch.object(paths, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        environment = patch.dict(os.environ, {"TEMP": str(self.legacy_temp)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.pc_relative = Path("pc/Vainglory 4.13/Vainglory/Data")

    def make_legacy_data(self):
        for path in (self.legacy_vg / self.pc_relative,
                     self.legacy_temp / "vg_max", self.legacy_temp / "vg_phaseB",
                     self.legacy_temp / "halcyon_stack"):
            path.mkdir(parents=True)

    def test_fresh_checkout_returns_local_paths_without_creating_them(self):
        local = self.project / "Local"
        self.assertEqual(paths.project_root(), self.project)
        self.assertEqual(paths.local_root(), local)
        self.assertEqual(paths.pc_data_dir(), local / "vainglory" / self.pc_relative)
        self.assertEqual(paths.research_dir("vg_max"), local / "research/vg_max")
        self.assertEqual(paths.stack_dir(), local / "runtime/halcyon_stack")
        self.assertFalse(local.exists())

    def test_legacy_corpora_still_work_before_migration(self):
        self.make_legacy_data()
        self.assertEqual(paths.pc_data_dir(), self.legacy_vg / self.pc_relative)
        self.assertEqual(paths.research_dir("vg_max"), self.legacy_temp / "vg_max")
        self.assertEqual(paths.stack_dir(), self.legacy_temp / "halcyon_stack")

    def test_local_directories_win_and_each_research_corpus_resolves_separately(self):
        self.make_legacy_data()
        local = self.project / "Local"
        for path in (local / "vainglory" / self.pc_relative,
                     local / "research/vg_max", local / "runtime/halcyon_stack"):
            path.mkdir(parents=True)
        self.assertEqual(paths.pc_data_dir(), local / "vainglory" / self.pc_relative)
        self.assertEqual(paths.research_dir("vg_max"), local / "research/vg_max")
        self.assertEqual(paths.research_dir("vg_phaseB"), self.legacy_temp / "vg_phaseB")
        self.assertEqual(paths.stack_dir(), local / "runtime/halcyon_stack")

    def test_explicit_root_does_not_silently_read_existing_legacy_data(self):
        self.make_legacy_data()
        selected = self.base / "separate private data"
        os.environ["HALCYON_LOCAL_ROOT"] = str(selected)
        self.assertEqual(paths.pc_data_dir(), selected / "vainglory" / self.pc_relative)
        self.assertEqual(paths.research_dir("vg_max"), selected / "research/vg_max")
        self.assertEqual(paths.stack_dir(), selected / "runtime/halcyon_stack")
        self.assertFalse(selected.exists())

    def test_relative_overrides_are_project_relative_from_another_working_directory(self):
        os.environ["HALCYON_LOCAL_ROOT"] = "Private data"
        os.environ["HALCYON_STACK_DIR"] = "Private runtime"
        previous = Path.cwd()
        try:
            os.chdir(self.base)
            self.assertEqual(paths.local_root(), self.project / "Private data")
            self.assertEqual(paths.stack_dir(), self.project / "Private runtime")
            self.assertEqual(paths.pc_data_dir(),
                             self.project / "Private data/vainglory" / self.pc_relative)
        finally:
            os.chdir(previous)

    def test_runtime_override_leaves_corpus_selection_unchanged(self):
        self.make_legacy_data()
        selected = self.base / "isolated runtime"
        os.environ["HALCYON_STACK_DIR"] = str(selected)
        self.assertEqual(paths.stack_dir(), selected)
        self.assertEqual(paths.research_dir("vg_max"), self.legacy_temp / "vg_max")
        self.assertEqual(paths.pc_data_dir(), self.legacy_vg / self.pc_relative)

    def test_runtime_templates_prefer_local_without_replacing_original_archive(self):
        self.make_legacy_data()
        runtime = self.project / "Local/research/runtime-corpus"
        runtime.mkdir(parents=True)
        self.assertEqual(paths.runtime_corpus_dir(), runtime)
        self.assertEqual(paths.research_dir("vg_phaseB"), self.legacy_temp / "vg_phaseB")

    def test_runtime_templates_fall_back_to_selected_original_archive(self):
        self.make_legacy_data()
        self.assertEqual(paths.runtime_corpus_dir(), self.legacy_temp / "vg_phaseB/vgr_live")
        original = self.project / "Local/research/vg_phaseB"
        original.mkdir(parents=True)
        self.assertEqual(paths.runtime_corpus_dir(), original / "vgr_live")

    def test_explicit_root_selects_runtime_templates_without_original_archive_fallback(self):
        self.make_legacy_data()
        selected = self.base / "separate private data"
        os.environ["HALCYON_LOCAL_ROOT"] = str(selected)
        self.assertEqual(paths.runtime_corpus_dir(), selected / "research/runtime-corpus")
        self.assertFalse(selected.exists())

    def test_research_name_cannot_escape_selected_root(self):
        for name in ("", ".", "..", "../vg_max", "vg_max/vgr", "vg_max\\vgr", "C:vg_max"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.research_dir(name)

    def test_spawn_corpus_override_and_explicit_argument_remain_authoritative(self):
        from server import entity_spawn

        first, second = self.base / "first corpus", self.base / "second corpus"
        os.environ["HALCYON_LOCAL_ROOT"] = str(self.base / "unused")
        os.environ["HALCYON_SPAWN_CORPUS"] = os.pathsep.join(map(str, (first, second)))
        self.assertEqual(entity_spawn._source_paths(), (str(first), str(second)))
        self.assertEqual(entity_spawn._source_paths(self.base / "explicit"),
                         (str(self.base / "explicit"),))


if __name__ == "__main__":
    unittest.main()
