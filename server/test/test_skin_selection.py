"""Tests for hero skin resolution, manifest integration, and draft selection."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from server import abilities, hero_balance, hero_catalog, match_server, roster, wire
from server.hero_movement import HeroMovement


class TestSkinManifest(unittest.TestCase):
    def test_answers_json_manifest_and_unlocks(self):
        answers_path = Path("Local/runtime/halcyon_stack/answers.json")
        if not answers_path.is_file():
            self.skipTest("Local answers.json not available")
        data = json.loads(answers_path.read_text(encoding="utf-8"))
        self.assertIn("getSkinManifest", data)
        manifest_raw = data["getSkinManifest"]
        self.assertIn("returnValue", manifest_raw)
        manifest = json.loads(manifest_raw["returnValue"])
        self.assertIn("skins", manifest)
        self.assertGreater(len(manifest["skins"]), 200)
        self.assertIn("themes", manifest)
        self.assertGreater(len(manifest["themes"]), 100)

        for endpoint in ("startSessionForPlayer", "getPlayerForGuestAccount"):
            self.assertIn(endpoint, data)
            body = data[endpoint]["returnValue"]["playerInfo"]
            self.assertTrue(body.get("canUseAllHeroes"))
            unlocks = body.get("unlocks", [])
            self.assertGreaterEqual(len(unlocks), 275)


class TestHeroCatalogSkinResolution(unittest.TestCase):
    def test_is_skin_name(self):
        self.assertTrue(hero_catalog.is_skin_name("Skye_Skin_Eagle_T1"))
        self.assertTrue(hero_catalog.is_skin_name("Skye_Skin_Bike"))
        self.assertTrue(hero_catalog.is_skin_name("Skye_Skin_Exoframe"))
        self.assertTrue(hero_catalog.is_skin_name("Adagio_DefaultSkin"))
        self.assertFalse(hero_catalog.is_skin_name("Skye"))
        self.assertFalse(hero_catalog.is_skin_name("Catherine"))

    def test_get_base_hero_name(self):
        self.assertEqual(hero_catalog.get_base_hero_name("Skye_Skin_Eagle_T1"), "Skye")
        self.assertEqual(hero_catalog.get_base_hero_name("Skye_Skin_Bike"), "Skye")
        self.assertEqual(hero_catalog.get_base_hero_name("Adagio_DefaultSkin"), "Adagio")
        self.assertEqual(hero_catalog.get_base_hero_name("*Skye_Skin_Bike"), "Skye")
        self.assertEqual(hero_catalog.get_base_hero_name("Skye"), "Skye")

    def test_resolve_hero_name(self):
        self.assertEqual(hero_catalog.resolve_hero_name("Skye_Skin_Eagle_T1"), "Skye")
        self.assertEqual(hero_catalog.resolve_hero_name("Skye"), "Skye")
        self.assertEqual(hero_catalog.resolve_hero_name(265), "Skye")
        # Internal aliases
        self.assertEqual(hero_catalog.resolve_hero_name("Krul"), "Hero009")
        self.assertEqual(hero_catalog.resolve_hero_name("Taka"), "Sayoc")
        self.assertEqual(hero_catalog.resolve_hero_name("Skaarf"), "Hero010")
        self.assertEqual(hero_catalog.resolve_hero_name("Rona"), "Hero016")

    def test_resolve_hero_id(self):
        self.assertEqual(hero_catalog.resolve_hero_id("Skye"), 265)
        self.assertEqual(hero_catalog.resolve_hero_id("Skye_Skin_Eagle_T1"), 265)
        self.assertEqual(hero_catalog.resolve_hero_id("Skye_Skin_Bike"), 265)
        self.assertEqual(hero_catalog.resolve_hero_id(265), 265)

    def test_registry_ids_pass_through_unchanged(self):
        """Wire hero ids use the native registry space; unknown ids are not
        guessed from 1107 catalog indices (whose order is not an id space).

        The live client sends base-hero registry ids (measured 2026-09-13:
        c2s 1118 hero 925 = Amael); skins ride the selection hash, so the
        server must resolve the id it received, not re-map it.
        """
        self.assertEqual(hero_catalog.resolve_hero_id(925), 925)
        self.assertEqual(hero_catalog.resolve_hero_name(925), "Amael")
        self.assertEqual(hero_catalog.resolve_hero_id(254), 254)
        # Catalog index 57 is Adagio_Skin_Goth_T1; index order is not identity.
        self.assertNotEqual(hero_catalog.resolve_hero_name(57), "Adagio")
        self.assertEqual(hero_catalog.resolve_hero_name(57), "Hero_57")
        # Skin names still resolve through the catalog name table.
        self.assertEqual(hero_catalog.resolve_hero_name("Adagio_Skin_Goth_T1"), "Adagio")

    def test_all_catalog_entries_resolve_validly(self):
        skye_skins = [name for name in hero_catalog.HERO_CATALOG_1107_NAMES if "Skye" in name]
        self.assertIn("Skye_Skin_Eagle_T1", skye_skins)
        self.assertIn("Skye_Skin_Eagle_T2", skye_skins)
        self.assertIn("Skye_Skin_Eagle_T3", skye_skins)
        self.assertIn("Skye_Skin_Bike", skye_skins)
        self.assertIn("Skye_Skin_Exoframe", skye_skins)
        for name in skye_skins:
            self.assertEqual(hero_catalog.resolve_hero_id(name), 265)
            self.assertEqual(hero_catalog.resolve_hero_name(name), "Skye")


class TestRosterSkinIntegration(unittest.TestCase):
    def test_hero_init_for_skin_resolves_base_hero(self):
        adagio_skin = "Adagio_DefaultSkin"
        init_data, donated = roster.hero_init_for(hero_catalog.resolve_hero_id(adagio_skin))
        self.assertIsNotNone(init_data)
        self.assertFalse(donated)

    def test_build_hero_block_for_skin_populates_stats(self):
        player = roster.Player("TestPlayer", 1, 1500, 265, 0x12345678, "uuid-1", False)
        player.slot = 0
        block = roster.build_hero_block(player)
        self.assertEqual(len(block), 750)


class TestAbilityKitSkinIntegration(unittest.TestCase):
    def test_create_hero_kit_with_skye_skins(self):
        sim = HeroMovement(1500, 1)
        for skin in ("Skye_Skin_Eagle_T1", "Skye_Skin_Eagle_T2", "Skye_Skin_Eagle_T3",
                     "Skye_Skin_Bike", "Skye_Skin_Exoframe"):
            base_id = hero_catalog.resolve_hero_id(skin)
            kit = abilities.create_hero_kit(sim, base_id, hero_name=skin)
            self.assertIsInstance(kit, abilities.SkyeKit)
            self.assertEqual(kit.name, "Skye")


class TestMatchServerSkinDraft(unittest.TestCase):
    def _create_stream(self):
        players = roster.default_solo_bots("test-match", "test-match")
        stream = match_server.SnapshotStream(None, players, "test-match",
                                             lambda op, p: None, log=lambda _: None)
        return stream

    def test_skin_update_during_lock_phase(self):
        stream = self._create_stream()
        player = stream.players[0]
        player.hero_id = 265  # Skye
        player.selection_hash = 0x12345678
        player.pick_flags = roster.PICK_FLAG_LOCKED

        new_hash = 0x87654321
        payload = roster.build_hero_selection(player)
        payload = payload[:4] + new_hash.to_bytes(4, "big") + payload[8:]

        stream._apply_event(wire.OP.JOIN_1118, payload)
        self.assertEqual(player.hero_id, 265)
        self.assertEqual(player.selection_hash, new_hash)

    def test_different_hero_change_during_lock_phase_rejected(self):
        stream = self._create_stream()
        player = stream.players[0]
        player.hero_id = 265  # Skye
        player.selection_hash = 0x12345678
        player.pick_flags = roster.PICK_FLAG_LOCKED

        ringo_id = 243  # Ringo
        new_hash = 0x99999999
        payload = ringo_id.to_bytes(4, "big") + new_hash.to_bytes(4, "big") + bytes(6)

        stream._apply_event(wire.OP.JOIN_1118, payload)
        self.assertEqual(player.hero_id, 265)
        self.assertEqual(player.selection_hash, 0x12345678)

    def test_finalize_configures_base_stats_for_skin(self):
        stream = self._create_stream()
        player = stream.players[0]
        player.hero_id = hero_catalog.resolve_hero_id("Skye_Skin_Bike")
        stream._finalize()

        sim = stream.hero_sims[player.eid]
        self.assertEqual(sim.hero_id, 265)
        self.assertEqual(sim.max_hp, hero_balance.STATS["Skye"].health_base)
        self.assertIsInstance(stream.hero_kits[player.eid], abilities.SkyeKit)


class TestSkinSelectionCalibration(unittest.TestCase):
    """Explicit calibration comparing pre-fix failure modes with post-fix resolution."""

    def test_prefix_skin_lookup_failure_vs_postfix_resolution(self):
        # Known-bad / pre-fix calibration:
        # Looking up a skin name directly in hero_balance.STATS fails because skins
        # are cosmetic themes rather than separate balance entries.
        skin_name = "Skye_Skin_Bike"
        self.assertNotIn(skin_name, hero_balance.STATS)
        with self.assertRaises(KeyError):
            _ = hero_balance.STATS[skin_name]

        # Post-fix / known-good calibration:
        # Resolving via hero_catalog maps the skin name to canonical base hero "Skye".
        base_name = hero_catalog.resolve_hero_name(skin_name)
        self.assertEqual(base_name, "Skye")
        self.assertIn(base_name, hero_balance.STATS)
        self.assertEqual(hero_balance.STATS[base_name].health_base, 708.0)

    def test_prefix_lock_gate_dropped_cosmetics_vs_postfix_retention(self):
        # Pre-fix calibration: in match_server._apply_event, if pick_flags & PICK_FLAG_LOCKED,
        # the entire 1118 payload was discarded, preventing cosmetic skin selection after lock.
        # Post-fix calibration: cosmetic selection_hash is retained for the locked hero.
        stream = match_server.SnapshotStream(
            None, roster.default_solo_bots("m", "m"), "m",
            lambda op, p: None, log=lambda _: None,
        )
        player = stream.players[0]
        player.hero_id = 265
        player.selection_hash = 0
        player.pick_flags = roster.PICK_FLAG_LOCKED

        # Emulate pre-fix logic: if player.pick_flags & PICK_FLAG_LOCKED: return
        prefix_hash = player.selection_hash
        self.assertEqual(prefix_hash, 0)

        # Post-fix logic: accepts skin hash for locked hero
        new_skin_hash = 0xA1B2C3D4
        payload = (265).to_bytes(4, "big") + new_skin_hash.to_bytes(4, "big") + bytes(6)
        stream._apply_event(wire.OP.JOIN_1118, payload)
        self.assertEqual(player.selection_hash, new_skin_hash)


if __name__ == "__main__":
    unittest.main()
