"""Compare the complete item catalog with native structured metadata outside Git."""
import unittest

from server.paths import pc_data_dir
from server import cooldown_wire, economy, items
from Tools.Teardown.inspect_item_constants import read_item_stats, read_named_constants

STORE = pc_data_dir()
# Native manifest identities mapped to operator-owned CFF metadata paths. These
# are structural references, not copied proprietary payloads or asset content.
ITEM_FILES = {
    458: "D1/D1A5F3CCB64928EA2B673AC8196ECAFC",
    459: "28/2888F1D265ECA3AB4A259D81D14034BA",
    460: "5A/5A349BA50E28D14674A460B2CC78CC7C",
    461: "37/37E0690F48754A5D1034AC4CB576DB4E",
    462: "2F/2FA50101EEAD18B8CBC2BDE147C2D2B1",
    463: "81/81A9C11EBF7815DA14F12EBB2D274E30",
    464: "FF/FF43B0229CE335A1C2398566D8E400F7",
    465: "93/9301E2661C72451ABE093064F9086094",
    467: "35/35E84498C4DE5BDB96E9C3E8AF1A49FD",
    468: "80/80C4E8CBD09D5BD1DA7C633865DEFA87",
    469: "D3/D340B7892F72B2938BC0744EF25AA677",
    470: "F7/F77D1040EBEC89C9AC3CEEC59507997D",
    471: "57/57A1F08B38C7F550FC00A1150E9DD794",
    472: "D7/D7749281BC837F60816ABA3B3C0D48C2",
    473: "ED/ED5D152EC883D1706C6F8842E2E8A30F",
    474: "8C/8C781FF49D5EBEEE52CE416B906E68FA",
    475: "D2/D2E88E4BBF3D443BA8CCE897AF1ECE64",
    476: "21/21C0A6C42DFFDC17562EB889EC3D9151",
    477: "DC/DCC1C968EBDBADF3DBF0D3C6F3B578F3",
    478: "40/40CFE5C9860B38921165A2F89933236A",
    485: "AB/ABE806121DAD85A8E299F01E58AE9C51",
    487: "3A/3A4A448F2A4B2A65D84997E8DBC3784A",
    488: "2E/2E729BE9B5F19D6BCDCDE778A0A70442",
    490: "6D/6D88622FFB87BF474FADF47E0BE08A8E",
    492: "9C/9C3D878940AD124EE6B2061782ED5F44",
    498: "F3/F3C4F656562D438BA2A391D3D0C57E20",
    501: "B5/B5BBA5C2A27ACED680429668BCAED20A",
    502: "49/495123D6CD8D3D212859992A415B165F",
    503: "E9/E97E12703EFAFFD78A101D8F433A53B5",
    504: "6D/6DDEBC81D54A151903FD8ED28295DD87",
    505: "D1/D18B30344106454DAF7BB6DD0DCC82E9",
    509: "96/96E46D8E7727145F8ACC52C392016E94",
    512: "80/8084ECAB6EDA8E78FBDCBD3280561321",
    522: "CD/CD09B7C1BE6E33393BB6BA3BFEDF3433",
    525: "AB/ABFF72F05789D6566BD2389BFD300BFC",
    538: "C4/C48C06A6D05D70C860E77D24C7C26AB4",
}
ACTIVE_FILES = {
    485: "63/63B0469E8E1F2B6CEDB4B91D51BB24A8",  # Ability__Item__ReflexBlock
    503: "68/68339E2048F22E856D7A41937AF0776C",  # Ability__Item__UpgradedReflexBlock
}


@unittest.skipUnless(all((STORE / path).is_file() for path in (*ITEM_FILES.values(), *ACTIVE_FILES.values())),
                     "external native item metadata unavailable")
class TestNativeItemConstants(unittest.TestCase):
    def test_default_hud_item_cooldowns_and_totem_state_capacity_match_native_records(self):
        player = economy.PlayerEconomy(1500)
        for instance, path in ((2000, "AF/AFE27DA418272F58FF795339B0DE791F"),
                               (2001, "74/74B1975A1D1590FA748ADD33740A56B4")):
            if not (STORE / path).is_file():
                self.skipTest("external default item metadata unavailable")
            fields = {"cooldown"} if instance == 2000 else {"cooldown", "charges"}
            values = {row["name"].casefold(): row["coefficients"]
                      for row in read_named_constants(STORE / path, fields)}
            self.assertEqual(values["cooldown"], (player.default_items[instance].cooldown, 0, 0, 0))
            if instance == 2001:
                self.assertEqual(values["charges"], (player.default_items[instance].native_state_count, 0, 0, 0))

    def test_all_36_catalog_item_attributes_match_native_records_including_zero_fields(self):
        fields = {0: "max_hp", 2: "max_energy", 3: "energy_regen", 4: "weapon_power",
                  5: "crystal_power", 7: "armor", 8: "shield", 15: "attack_speed",
                  25: "cooldown_reduction"}
        self.assertEqual(set(economy.ITEMS), set(ITEM_FILES))
        for item_id, path in ITEM_FILES.items():
            records = read_item_stats(STORE / path)
            native = {record["attribute"]: record["value"] for record in records}
            self.assertEqual(len(native), len(records), item_id)
            self.assertTrue(set(native) <= set(fields), f"unmapped attribute for item {item_id}")
            item = economy.ITEMS[item_id]
            for attribute, field in fields.items():
                expected = getattr(item, field) / (100.0 if attribute == 15 else 1.0)
                self.assertAlmostEqual(native.get(attribute, 0.0), expected, places=7,
                                       msg=f"{item.name}: {field}")

    def test_every_catalog_active_cooldown_matches_its_native_ability_record(self):
        checked = 0
        for item_id, item in economy.ITEMS.items():
            if not item.active:
                continue
            path = ACTIVE_FILES.get(item_id, ITEM_FILES[item_id])
            records = read_named_constants(STORE / path, {"cooldown"})
            self.assertEqual(len(records), 1, item.name)
            self.assertEqual(records[0]["coefficients"], (item.cooldown, 0.0, 0.0, 0.0), item.name)
            key = item.name.lower().replace(" ", "_")
            self.assertEqual(item.cooldown, cooldown_wire.NATIVE_ITEM_COOLDOWNS[key])
            checked += 1
        self.assertEqual(checked, 8)

    def test_boots_static_move_speed_uses_move_not_the_separate_travel_modifier(self):
        for item_id in (477, 478, 490):
            values = read_named_constants(STORE / ITEM_FILES[item_id], {"move"})
            self.assertEqual(len(values), 1)
            self.assertAlmostEqual(values[0]["coefficients"][0], economy.ITEMS[item_id].move_speed, places=7)

    def test_unspecified_item_rule_values_use_exact_native_named_records(self):
        rules = items.ItemRules()
        expected = {492: {"cooldown": rules.aftershock_cooldown},
                    522: {"damage_duration": rules.spellfire_duration,
                          "ticks_per_second": rules.spellfire_ticks_per_second},
                    525: {"burst_window": rules.husk_burst_window,
                          "fortified_health_duration": rules.husk_duration,
                          "lockout_duration": rules.husk_cooldown},
                    487: {"range": rules.ally_radius}, 488: {"range": rules.ally_radius}}
        for item_id, fields in expected.items():
            records = read_named_constants(STORE / ITEM_FILES[item_id], set(fields))
            self.assertEqual({row["name"].casefold() for row in records}, set(fields))
            for record in records:
                self.assertEqual(record["coefficients"], (fields[record["name"].casefold()], 0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
