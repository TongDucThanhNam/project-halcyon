"""Optional steering preserves collision gates and fixed-tick3D travel budgets."""
import unittest
from unittest.mock import Mock
from server.hero_movement import HeroMovement
from server.navigation import NavMesh
from server.native_steering import NativeSteeringMesh, SurfacePath


class NativeSteeringTests(unittest.TestCase):
    def mesh(self,points,*,height=4):
        mesh=NavMesh([(0,0),(6,0),(6,4),(0,4)],[(0,1,2),(0,2,3)],heights=[0,height*2,height*2,0])
        query=Mock(manifest={'library_sha256':'test-query'})
        query.query.return_value={'points':points,'capped':False,'ended':True,
                                  'destination_polygon_reached':True,'height_fallbacks':0}
        return NativeSteeringMesh(mesh,query)

    def test_three_four_five_slope_uses_surface_distance_not_planar_shortcut(self):
        mesh=self.mesh([[0,0,1],[3,4,1]])
        hero=HeroMovement(x=0,y=1,speed=5,navigation=mesh)
        hero.set_target(3,1)
        hero.step(.5)
        self.assertEqual(hero.position_fixed,(1500000,1000000))
        self.assertEqual(hero.waypoints.cursor_height_fixed,2000000)
        hero.step(.5)
        self.assertFalse(hero.is_moving)
        self.assertEqual(hero.position_fixed,(3000000,1000000))

    def test_fixed_ticks_cross_surface_waypoints_without_extra_time(self):
        mesh=self.mesh([[0,0,1],[.75,1,1],[1.5,2,1],[3,4,1]])
        positions=[]
        for _ in range(2):
            hero=HeroMovement(x=0,y=1,speed=5,navigation=mesh)
            hero.set_target(3,1)
            sequence=[]
            for _ in range(20):
                hero.step(.05);sequence.append(hero.position_fixed)
            self.assertFalse(hero.is_moving)
            self.assertEqual(hero.position_fixed,(3000000,1000000))
            positions.append(sequence)
        self.assertEqual(*positions)

    def test_retarget_preserves_interpolated_height_as_new_query_origin(self):
        mesh=self.mesh([[0,0,1],[3,4,1]])
        hero=HeroMovement(x=0,y=1,speed=5,navigation=mesh)
        hero.set_target(3,1);hero.step(.5)
        mesh.query.query.return_value['points']=[[1.5,2,1],[2.25,3,1]]
        hero.set_target(2.25,1)
        self.assertEqual(mesh.query.query.call_args.args[0],[1.5,2,1])
        hero.step(.25)
        self.assertFalse(hero.is_moving)
        self.assertEqual(hero.position_fixed,(2250000,1000000))

    def test_pursuit_range_clamp_converts_planar_reach_to_surface_budget(self):
        mesh=self.mesh([[0,0,1],[3,4,1]])
        hero=HeroMovement(x=0,y=1,speed=5,attack_range=1,navigation=mesh)
        hero.set_target_eid(1517)
        for tick in range(14):
            hero.step(.05,now=tick*.05,target_pos=(3,1))
        self.assertGreaterEqual(hero.x,2)
        self.assertLess(hero.x,2.000005)
        hero.step(.05,now=.7,target_pos=(3,1))
        self.assertFalse(hero.is_moving)

    def test_capped_query_does_not_silently_replace_requested_destination(self):
        mesh=self.mesh([[0,0,1],[1,0,1]],height=0)
        mesh.query.query.return_value.update(capped=True,ended=False)
        route=mesh.find_path_with_height((0,1),(5,1))
        self.assertNotIsInstance(route,SurfacePath)
        self.assertEqual(route[-1],(5,1))
        self.assertEqual(mesh.query_counts['fallback:partial-or-capped'],1)

    def test_unqualified_surface_point_cannot_bypass_collision_guard(self):
        mesh=self.mesh([[0,0,1],[10,0,1]],height=0)
        route=mesh.find_path_with_height((0,1),(3,1))
        self.assertNotIsInstance(route,SurfacePath)
        self.assertEqual(route[-1],(3,1))
        self.assertEqual(mesh.query_counts['fallback:surface-projection'],1)

    def test_height_query_failure_retains_old_policy_with_explicit_counter(self):
        mesh=self.mesh([[0,0,1],[3,0,1]],height=0)
        mesh.query.query.return_value['height_fallbacks']=1
        self.assertNotIsInstance(mesh.find_path_with_height((0,1),(3,1)),SurfacePath)
        self.assertEqual(mesh.query_counts['fallback:height-query'],1)

    def test_disabled_path_keeps_existing_planar_motion(self):
        mesh=NavMesh([(0,0),(6,0),(6,4),(0,4)],[(0,1,2),(0,2,3)],heights=[0,8,8,0])
        hero=HeroMovement(x=0,y=1,speed=5,navigation=mesh)
        hero.set_target(3,1);hero.step(.5)
        self.assertEqual(hero.position_fixed,(2500000,1000000))

    def test_rounding_before_a_tangent_corner_preserves_the_remaining_segment(self):
        # An L-shaped walkable union. The direct line grazes (0,0); an
        # initially harmless downward rounding error would later cut the wall.
        mesh=NavMesh([(-3,-3),(0,-3),(0,0),(0,3),(-3,3),(3,0),(3,3)],
                     [(0,1,2),(0,2,3),(0,3,4),(2,5,6),(2,6,3)])
        hero=HeroMovement(x=-2,y=-1,speed=3.7,navigation=mesh)
        hero.set_target(2,1)
        for _ in range(30):
            previous=(hero.x,hero.y)
            hero.step(.05)
            self.assertTrue(mesh.segment_walkable(previous,(hero.x,hero.y)))
            if hero.waypoints:
                self.assertTrue(mesh.segment_walkable((hero.x,hero.y),hero.waypoints[0]))
        self.assertFalse(hero.is_moving)

    def test_canonical_production_state_includes_interpolated_surface_height(self):
        from types import SimpleNamespace
        from server.navigation import DEFAULT_CLASSIC_NAVMESH
        if not DEFAULT_CLASSIC_NAVMESH.is_file():
            self.skipTest('owned Classic geometry unavailable')
        from Tools.run_scenarios import build_world
        from Tools.verify_sandbox import freeze_state
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{'HALCYON_NO_TAPE':'1','HALCYON_QA_DIR':''}):
            world,_,_,_=build_world(DEFAULT_CLASSIC_NAVMESH,'surface-state-test')
        hero=world.hero_sims[1500]
        hero.waypoints=SurfacePath([(1,1)],[2],1)
        before=freeze_state(world,SimpleNamespace(state={}), 'mesh-digest')
        hero.waypoints.cursor_height_fixed+=1
        self.assertNotEqual(before,freeze_state(world,SimpleNamespace(state={}), 'mesh-digest'))


if __name__ == '__main__':
    unittest.main()
