"""Independent source-name guards for native 1037 launch-socket hashes."""
import unittest

from server.paths import pc_data_dir, research_dir
from Tools.Teardown.inspect_projectile_sockets import read_projectile_sockets


class ProjectileSocketMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = pc_data_dir()
        names = research_dir('vg_max') / 'inst_names.tsv'
        if not root.is_dir() or not names.is_file():
            raise unittest.SkipTest('operator-owned unit store/name index unavailable')
        cls.paths = {row[0]: root / row[1] for line in names.read_text().splitlines()
                     if len(row := line.split('\t')) >= 2}

    def sockets(self, name):
        result = read_projectile_sockets(self.paths[name])
        return result, {entry['name']: entry for entry in result['sockets']}

    def test_adagio_native_default_attack_hash_matches_its_socket_name(self):
        result, sockets = self.sockets('Adagio')
        self.assertEqual(result['skin'], 'Adagio_DefaultSkin')
        self.assertEqual(sockets['DefaultAttack_Projectile'], {
            'index': 6, 'name': 'DefaultAttack_Projectile', 'hash': '855a7534',
            'record_offset': 9456, 'name_offset': 9496})

    def test_skye_native_alternating_launch_hashes_are_distinct_named_sockets(self):
        result, sockets = self.sockets('Skye')
        self.assertEqual(result['skin'], 'Skye_DefaultSkin')
        self.assertEqual(sockets['LeftGun']['hash'], '77b4b72a')
        self.assertEqual(sockets['RightGun']['hash'], 'b1ab2985')
        self.assertEqual((sockets['LeftGun']['record_offset'], sockets['RightGun']['record_offset']),
                         (13228, 13276))

    def test_native_ranged_minion_launch_hash_is_gun_muzzle(self):
        result, sockets = self.sockets('HF_Minion_Range')
        self.assertEqual(result['skin'], 'Minion_DefaultSkin')
        self.assertEqual(sockets['GunMuzzle']['hash'], '005dd10c')
        self.assertEqual(sockets['GunMuzzle']['name_offset'], 2660)

    def test_other_corpus_confirmed_launches_match_owned_socket_names(self):
        expected = {
            'Vox': {'BasicAttack_RightHand': '17f2cf05'},
            'Kestrel': {'DefaultAttack_Spawn': 'e3a0d5ba', 'AltAttack_Spawn': 'bf31a0f8'},
            'Lorelai': {'CenterBody': '3e3270a0'},
            'Magnus': {'A_Projectile': '84e975e6'},
            'Silvernail': {'Projectile': '713f51ba'},
            'Caine': {'AutoAttack': '95982642'},
            'Viola': {'AutoAttack': '95982642'},
        }
        for hero, hashes in expected.items():
            with self.subTest(hero=hero):
                _, sockets = self.sockets(hero)
                for name, expected_hash in hashes.items():
                    self.assertEqual(sockets[name]['hash'], expected_hash)

    def test_uncaptured_ordinary_socket_candidates_do_not_invent_projectile_kind_ids(self):
        expected = {
            'Ringo': {'GunMuzzleTip_Attack': '97210b3e', 'GunMuzzleTip_AltAttack': 'c9c38069'},
            'Gwen': {'AA_1': '8bcfc1eb'},
            'Celeste': {'Mouth': '4620047c', 'Mouth_Alt': 'fed27c48'},
        }
        for hero, hashes in expected.items():
            with self.subTest(hero=hero):
                result, sockets = self.sockets(hero)
                self.assertEqual(result['skin'], hero + '_DefaultSkin')
                for name, expected_hash in hashes.items():
                    self.assertEqual(sockets[name]['hash'], expected_hash)


if __name__ == '__main__':
    unittest.main()
