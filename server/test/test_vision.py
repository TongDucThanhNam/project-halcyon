"""Unit tests for Project Halcyon FoW, shared team vision, and brush masking."""
import unittest

from server import hero_movement, jungle, structures, vision


class TestVisionManager(unittest.TestCase):
    def setUp(self):
        self.vm = vision.VisionManager()
        self.hero_t1 = hero_movement.HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        self.hero_t2 = hero_movement.HeroMovement(eid=1515, team=2, x=6.0, y=0.0)
        self.all_heroes = {1500: self.hero_t1, 1515: self.hero_t2}

    def test_allies_always_visible(self):
        # Two allies far apart (50u away)
        ally1 = hero_movement.HeroMovement(eid=1500, team=1, x=-50.0, y=0.0)
        ally2 = hero_movement.HeroMovement(eid=1501, team=1, x=50.0, y=0.0)
        heroes = {1500: ally1, 1501: ally2}

        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=heroes)
        visible = self.vm.is_visible_to_team(
            target_team=1, target_x=ally2.x, target_y=ally2.y,
            target_eid=ally2.eid, team=1, sources=sources, now=0.0
        )
        self.assertTrue(visible)

    def test_enemy_visible_within_vision_radius(self):
        # Enemy at 6.0u (within 10.0u radius) in open terrain
        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=self.all_heroes)
        visible = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=0.0
        )
        self.assertTrue(visible)

    def test_enemy_hidden_beyond_vision_radius(self):
        # Move enemy to 15.0u (beyond 10.0u hero radius)
        self.hero_t2.x = 15.0
        self.hero_t2.y = 0.0

        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=self.all_heroes)
        visible = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=0.0
        )
        self.assertFalse(visible)

    def test_brush_masks_enemy_from_outside_observer(self):
        # Enemy is inside river brush (-4..4, 13..17), e.g. at (0.0, 15.0)
        self.hero_t2.x = 0.0
        self.hero_t2.y = 15.0
        self.assertTrue(jungle.JungleManager.is_in_brush(self.hero_t2.x, self.hero_t2.y))

        # Observer is outside brush at (0.0, 10.0) -> distance is only 5.0u (< 10.0u radius!)
        self.hero_t1.x = 0.0
        self.hero_t1.y = 10.0
        self.assertFalse(jungle.JungleManager.is_in_brush(self.hero_t1.x, self.hero_t1.y))

        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=self.all_heroes)
        visible = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=0.0
        )
        # Hidden by brush!
        self.assertFalse(visible)

    def test_brush_revealed_when_ally_enters_same_brush(self):
        # Both heroes enter the same river brush
        self.hero_t2.x = 0.0
        self.hero_t2.y = 15.0
        self.hero_t1.x = 1.0
        self.hero_t1.y = 15.0

        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=self.all_heroes)
        visible = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=0.0
        )
        # Visible because observer is inside the same brush!
        self.assertTrue(visible)

    def test_turret_truesight_reveals_brush(self):
        # Enemy is in brush at (0.0, 15.0)
        self.hero_t2.x = 0.0
        self.hero_t2.y = 15.0

        # Turret on team 1 at (0.0, 18.0) has TrueSight within 9.0u radius
        sm = structures.StructureManager()
        turret = next(iter(sm.structures.values()))
        turret.team = 1
        turret.x = 0.0
        turret.y = 18.0
        turret.is_alive = True

        sources = self.vm.collect_team_vision_sources(
            team=1, all_heroes={}, structures={turret.eid: turret}
        )
        visible = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=0.0
        )
        # Revealed by turret TrueSight!
        self.assertTrue(visible)

    def test_reveal_buff_overrides_brush(self):
        # Enemy is in brush at (0.0, 15.0)
        self.hero_t2.x = 0.0
        self.hero_t2.y = 15.0
        # Observer is outside brush at (0.0, 10.0)
        self.hero_t1.x = 0.0
        self.hero_t1.y = 10.0

        # Reveal enemy for 3.0s
        self.vm.reveal_entity(self.hero_t2.eid, duration=3.0, now=10.0)

        sources = self.vm.collect_team_vision_sources(team=1, all_heroes=self.all_heroes)
        visible_during = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=11.0
        )
        self.assertTrue(visible_during)

        # After duration expires: hidden again
        visible_after = self.vm.is_visible_to_team(
            target_team=2, target_x=self.hero_t2.x, target_y=self.hero_t2.y,
            target_eid=self.hero_t2.eid, team=1, sources=sources, now=14.0
        )
        self.assertFalse(visible_after)


if __name__ == "__main__":
    unittest.main()
