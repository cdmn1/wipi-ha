import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class NaomiPatchTests(unittest.TestCase):
    def test_illvelo_force_freeplay_is_unchanged(self):
        data = bytearray(0x620C8)
        data[0x620C6:0x620C8] = bytes.fromhex("42 84")
        patched = app.apply_illvelo_force_freeplay(bytes(data))
        self.assertEqual(patched[0x620C6:0x620C8], bytes.fromhex("1A E0"))
        self.assertEqual(patched[:0x620C6], bytes(data[:0x620C6]))

    def test_new_patch_options_are_game_specific_and_disabled_by_default(self):
        expected = {
            "CrazyTaxi.bin": ("Crazy Taxi", {
                "crazy_taxi_force_freeplay", "crazy_taxi_silent_attract", "crazy_taxi_noprotect"
            }),
            "Jambo_Safari.bin": ("Jambo Safari", {
                "jambo_safari_force_freeplay", "jambo_safari_silent_attract", "jambo_safari_noprotect"
            }),
            "mvsc2.bin": ("Marvel vs. Capcom 2", {
                "marvel_vs_capcom_2_unlocked", "marvel_vs_capcom_2_force_freeplay",
                "marvel_vs_capcom_2_silent_attract"
            }),
            "cvs2motm.bin": ("Capcom vs. SNK 2: Mark of the Millennium 2001", {
                "capcom_vs_snk_2_motm_unlocked", "capcom_vs_snk_2_motm_force_freeplay",
                "capcom_vs_snk_2_motm_silent_attract"
            }),
            "cvs2mf.bin": ("Capcom vs. SNK 2: Millionaire Fighting 2001", {
                "capcom_vs_snk_2_mf_unlocked", "capcom_vs_snk_2_mf_force_freeplay",
                "capcom_vs_snk_2_mf_silent_attract"
            }),
            "capsnk.bin": ("Capcom vs. SNK: Millennium Fight 2000", {
                "capcom_vs_snk_force_freeplay", "capcom_vs_snk_silent_attract"
            }),
        }
        for filename, (name, wanted) in expected.items():
            game = {
                "filename": filename, "name": name, "description": name,
                "audit_name": "", "game_id": "",
            }
            with self.subTest(game=name), patch.object(app, "load_patch_settings", return_value={}):
                options = app.game_patch_options(game)
                self.assertEqual({entry["id"] for entry in options}, wanted)
                self.assertTrue(all(not entry["enabled"] for entry in options))

    def test_upstream_patch_files_have_file_size_and_expected_byte_guards(self):
        patch_ids = (
            "crazy_taxi_force_freeplay", "crazy_taxi_silent_attract", "crazy_taxi_noprotect",
            "jambo_safari_force_freeplay", "jambo_safari_silent_attract", "jambo_safari_noprotect",
            "marvel_vs_capcom_2_unlocked",
            "capcom_vs_snk_2_motm_unlocked", "capcom_vs_snk_2_mf_unlocked",
        )
        for patch_id in patch_ids:
            with self.subTest(patch=patch_id):
                definition = app.PATCH_DEFINITIONS[patch_id]
                lines = (app.PATCHES_DIR / definition["patch_file"]).read_text(encoding="utf-8").splitlines()
                self.assertTrue(any(line.strip().lower().startswith("# file size:") for line in lines))
                self.assertTrue(any(" -> " in line for line in lines))

    def test_binary_diff_helper_applies_only_matching_size_and_preimage(self):
        with tempfile.TemporaryDirectory() as directory:
            patch_file = Path(directory) / "small.binpatch"
            patch_file.write_text(
                "# Description: unit test\n# File size: 8\n2: 11 22 -> AA BB\n",
                encoding="utf-8",
            )
            definition = {"title": "Small test patch", "patch_file": "small.binpatch"}
            with patch.object(app, "PATCHES_DIR", Path(directory)):
                with patch.dict(app.PATCH_DEFINITIONS, {"unit_test_patch": definition}):
                    original = bytes.fromhex("00 00 11 22 00 00 00 00")
                    self.assertEqual(
                        app.apply_binary_patch(original, "unit_test_patch"),
                        bytes.fromhex("00 00 AA BB 00 00 00 00"),
                    )
                    with self.assertRaisesRegex(ValueError, "preconditions"):
                        app.apply_binary_patch(bytes.fromhex("00 00 11 23 00 00 00 00"), "unit_test_patch")
                    with self.assertRaisesRegex(ValueError, "preconditions"):
                        app.apply_binary_patch(bytes.fromhex("00 00 11 22"), "unit_test_patch")

    def test_serial_specific_binary_patch_rejects_wrong_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            patch_file = Path(directory) / "serial.binpatch"
            patch_file.write_text("# File size: 4\n1: 11 -> 22\n", encoding="utf-8")
            definition = {
                "title": "Serial-specific test patch",
                "patch_file": "serial.binpatch",
                "required_serial": "BBG0",
            }

            class FakeRom:
                def __init__(self, data, serial):
                    self.valid = True
                    self.serial = serial

            with patch.object(app, "PATCHES_DIR", Path(directory)):
                with patch.dict(app.PATCH_DEFINITIONS, {"serial_test_patch": definition}):
                    with patch.object(app, "NaomiRom", lambda data: FakeRom(data, b"NOPE")):
                        with self.assertRaisesRegex(ValueError, "requires Naomi ROM serial BBG0"):
                            app.apply_binary_patch(bytes.fromhex("00 11 00 00"), "serial_test_patch")
                    with patch.object(app, "NaomiRom", lambda data: FakeRom(data, b"BBG0")):
                        self.assertEqual(
                            app.apply_binary_patch(bytes.fromhex("00 11 00 00"), "serial_test_patch"),
                            bytes.fromhex("00 22 00 00"),
                        )

    def test_documented_single_byte_patch_enforces_exact_size_when_declared(self):
        with self.assertRaisesRegex(ValueError, "expected exactly"):
            app.apply_documented_byte_patch(b"short", "capcom_vs_snk_force_freeplay")

    def test_removed_sfz3_region_unlock_is_filtered_from_legacy_profiles(self):
        self.assertNotIn("naomi_region_unlock", app.PATCH_DEFINITIONS)
        game = {
            "filename": "sfz3upper.bin",
            "name": "Street Fighter Zero 3 Upper",
            "description": "Street Fighter Zero 3 Upper",
            "audit_name": "",
            "game_id": "BCY0",
        }
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "patch_settings.json"
            settings_path.write_text(json.dumps({
                "sfz3upper.bin": ["naomi_region_unlock"]
            }), encoding="utf-8")
            with patch.object(app, "PATCH_SETTINGS_FILE", settings_path):
                self.assertEqual(app.load_patch_settings(), {})
                options = app.game_patch_options(game)
                self.assertNotIn("naomi_region_unlock", {entry["id"] for entry in options})
                self.assertEqual(
                    app.apply_game_patches(b"ROM", "sfz3upper.bin", {"target": "naomi"}),
                    (b"ROM", []),
                )

    def test_catalogued_upstream_patches_have_complete_expected_bytes(self):
        patch_ids = [
            patch_id for patch_id, definition in app.PATCH_DEFINITIONS.items()
            if definition.get("patch_file")
        ]
        self.assertTrue(patch_ids)
        for patch_id in patch_ids:
            definition = app.PATCH_DEFINITIONS[patch_id]
            patch_path = app.PATCHES_DIR / definition["patch_file"]
            lines = patch_path.read_text(encoding="utf-8").splitlines()
            self.assertIsNotNone(app.BinaryDiff.size(lines), patch_id)
            hunks = [line.strip() for line in lines
                     if line.strip() and not line.strip().startswith("#")]
            self.assertTrue(hunks, patch_id)
            for line in hunks:
                with self.subTest(patch=patch_id, hunk=line):
                    offset_text, changes = line.split(":", 1)
                    before_text, after_text = changes.split("->", 1)
                    before = before_text.strip().split()
                    after = after_text.strip().split()
                    self.assertGreaterEqual(int(offset_text.strip(), 16), 0)
                    self.assertEqual(len(before), len(after))
                    self.assertTrue(before)
                    self.assertTrue(all(len(token) == 2 and
                                        all(char in "0123456789abcdefABCDEF" for char in token)
                                        for token in before),
                                    "Every source byte must be explicit; wildcards are forbidden")
                    self.assertTrue(all(len(token) == 2 and
                                        all(char in "0123456789abcdefABCDEF" for char in token)
                                        for token in after))

    def test_binary_diff_preconditions_reject_wildcards(self):
        patch_lines = ["# File size: 4", "1: 11 * -> 22 33"]
        with self.assertRaisesRegex(ValueError, "Wildcard precondition"):
            app.binary_patch_preconditions_match(bytes.fromhex("00 11 22 00"), patch_lines)

    def test_multi_hunk_binary_patch_fails_if_any_preimage_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            patch_file = Path(directory) / "multi.binpatch"
            patch_file.write_text(
                "# Description: atomic multi-hunk test\n"
                "# File size: 8\n"
                "2: 11 22 -> AA BB\n"
                "6: 33 -> CC\n",
                encoding="utf-8",
            )
            definition = {"title": "Multi-hunk test", "patch_file": "multi.binpatch"}
            original = bytes.fromhex("00 00 11 22 00 00 34 00")
            with patch.object(app, "PATCHES_DIR", Path(directory)):
                with patch.dict(app.PATCH_DEFINITIONS, {"multi_test_patch": definition}):
                    with self.assertRaisesRegex(ValueError, "preconditions"):
                        app.apply_binary_patch(original, "multi_test_patch")
            self.assertEqual(original, bytes.fromhex("00 00 11 22 00 00 34 00"))



if __name__ == "__main__":
    unittest.main()
