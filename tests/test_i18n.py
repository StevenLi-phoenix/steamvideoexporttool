"""Tests for the zh-cn/en translation tables and the JSON settings store."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steam_exporter import i18n, settings


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings_file = Path(self.temporary.name) / "settings.json"
        patcher = patch.object(settings, "SETTINGS_FILE", self.settings_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(i18n.set_language, "en")

    def test_locales_define_the_same_keys_with_nonempty_text(self):
        zh, en = i18n._STRINGS["zh-cn"], i18n._STRINGS["en"]
        self.assertEqual(set(zh), set(en))
        for table in (zh, en):
            for key, text in table.items():
                self.assertTrue(text.strip(), f"empty translation for {key}")

    def test_tr_formats_parameters_in_both_locales(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("btn_export", count=3), "Export selected (3)")
        i18n.set_language("zh-cn")
        self.assertEqual(i18n.tr("btn_export", count=3), "导出所选录像 (3)")

    def test_tr_falls_back_to_english_then_to_the_key(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("missing_key_xyz"), "missing_key_xyz")
        i18n.set_language("zh-cn")
        # A key present only in the English table falls back for zh users.
        with patch.dict(i18n._STRINGS["en"], {"only_en": "fallback"}):
            self.assertEqual(i18n.tr("only_en"), "fallback")

    def test_normalize_language_maps_families_and_rejects_rest(self):
        self.assertEqual(i18n.normalize_language("ZH_tw"), "zh-cn")
        self.assertEqual(i18n.normalize_language(" en-US "), "en")
        self.assertIsNone(i18n.normalize_language("fr"))
        self.assertIsNone(i18n.normalize_language(None))

    def test_detect_prefers_saved_settings_then_environment(self):
        self.settings_file.write_text(json.dumps({"language": "zh-cn"}), encoding="utf-8")
        self.assertEqual(i18n.detect_language(), "zh-cn")
        self.settings_file.unlink()
        with patch.dict(os.environ, {"STEAM_EXPORT_LANG": "en"}):
            self.assertEqual(i18n.detect_language(), "en")

    def test_set_language_persists_and_update_settings_merges(self):
        i18n.set_language("zh-cn", persist=True)
        self.assertEqual(json.loads(self.settings_file.read_text(encoding="utf-8")), {"language": "zh-cn"})
        settings.update_settings(output=r"D:\Exports")
        self.assertEqual(
            json.loads(self.settings_file.read_text(encoding="utf-8")),
            {"language": "zh-cn", "output": r"D:\Exports"},
        )
        self.assertEqual(settings.load_settings(self.settings_file)["output"], r"D:\Exports")

    def test_set_language_rejects_unknown_locales(self):
        with self.assertRaises(ValueError):
            i18n.set_language("fr")

    def test_current_language_caches_detection(self):
        with patch.object(i18n, "_language", None):  # reset the cache
            with patch.object(i18n, "detect_language", return_value="zh-cn"):
                self.assertEqual(i18n.current_language(), "zh-cn")
            with patch.object(i18n, "detect_language", return_value="en"):
                self.assertEqual(i18n.current_language(), "zh-cn")  # cached on first call
        i18n.set_language("en")
        self.assertEqual(i18n.current_language(), "en")

    def test_load_settings_returns_empty_dict_for_garbage(self):
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text("not json {", encoding="utf-8")
        self.assertEqual(settings.load_settings(self.settings_file), {})
        self.assertEqual(settings.load_settings(self.settings_file.parent / "absent.json"), {})


if __name__ == "__main__":
    unittest.main()
