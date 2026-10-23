"""Ordinary gateway socket acceptance; no privileged gameplay preparation."""
import json
import copy
import struct
import threading
import time
import unittest
from unittest.mock import Mock, patch

from Tools import protocol_participants as pp
from server import gateway, match_server, paths
from server import roster, hero_catalog


def mixed_declaration(real_count=1, *, evidenced=False):
    identities = ['test-'+hero.lower() for hero in pp.HEROES]
    opponents = ['test-ringo', 'test-skye', 'test-gwen', 'test-catherine', 'test-amael', 'test-adagio']
    rows = [{'identity': identity, 'hero': hero, 'opponent': opponent}
            for identity, hero, opponent in zip(identities, pp.HEROES, opponents)]
    for i in range(real_count):
        rows[i].update(slot=pp.SLOTS[i], eid=pp.EIDS[i], team=1 if pp.SLOTS[i] < 3 else 2)
    if real_count == 2:
        rows[2]['opponent'] = 'test-ringo'
        rows[3]['opponent'] = 'test-skye'
    if evidenced:
        # Explicit authorized per-slot replacements; identities/opponents stay
        # fixed. No CE hash has been retained for Ringo or Gwen.
        for i in range(real_count, 6):
            if rows[i]['hero'] in ('Ringo', 'Gwen'):
                rows[i]['hero'] = hero_catalog.resolve_hero_name(roster.BOT_HERO_CHOICES[pp.SLOTS[i]-1][0])
    return {'real_clients': rows[:real_count], 'participants': rows[real_count:]}


def mixed_snapshot(plan, *, bots=False):
    players = []
    for i, row in enumerate(plan['real_clients']+plan['participants']):
        player = roster.Player(row['hero'], 1 if pp.SLOTS[i] < 3 else 2, pp.EIDS[i],
                               hero_catalog.resolve_hero_id(row['hero']), 0, row['identity'], False)
        player.slot = pp.SLOTS[i]
        player.pick_flags = roster.PICK_FLAG_SELECTED
        if bots and row in plan['participants']:
            player.uuid, player.hero_id, player.is_bot = roster.BOT_UUID_SENTINEL, 0xffff, True
            player.pick_flags = 0
        players.append(player)
    return roster.build_snapshot(sorted(players, key=lambda p:p.slot))


class TestSelectionHashes(unittest.TestCase):
    def test_measured_selection_and_commit_pairs_and_sources(self):
        expected = {265: (0xf59cdb08, 0xd063a8b6), 242: (0x62dbdc96, 0xc3c86a12),
                    925: (0x2fd7245d, 0x4260123e), 396: (0xbc155def, 0xbc155def),
                    244: (0xf9fd7554, 0xf9fd7554), 399: (0x4a490296, 0x4a490296),
                    254: (0x9d1ad5d3, 0x9d1ad5d3), 924: (0xe25acb56, 0xe25acb56)}
        for hero_id, hashes in expected.items():
            with self.subTest(hero_id=hero_id):
                selected, committed, source = pp.selection_hashes(hero_id)
                self.assertEqual((selected, committed), hashes)
                self.assertTrue(source)
                p = Mock(hero_id=hero_id, identity='participant')
                selection, commit = pp.draft_payloads([p])['participant']
                self.assertEqual(struct.unpack('>II', selection[:8]), (hero_id, selected))
                self.assertEqual(selection[8:], bytes(6))
                self.assertEqual(commit, struct.pack('>I', committed)+bytes(2))
                self.assertEqual(p.hash_evidence['source'], source)

    def test_missing_hash_refuses_both_entry_paths_before_any_connection_or_input(self):
        for hero_id in (243, 395, 0xffff):
            for enter in ('mixed', 'wire-only'):
                players = [Mock(hero_id=265, identity='known'), Mock(hero_id=hero_id, identity='unknown')]
                mixed = Mock()
                with self.subTest(hero_id=hero_id, enter=enter), self.assertRaisesRegex(pp.StageFailure, 'no evidenced'):
                    if enter == 'mixed':
                        pp.enter_mixed(players, mixed)
                    else:
                        pp.enter_world(players)
                mixed.wait_admission.assert_not_called()
                for p in players:
                    p.connect.assert_not_called()
                    p.input.assert_not_called()

    def test_bot_bisection_is_explicit_and_keeps_slot_order(self):
        declaration = mixed_declaration()
        original = copy.deepcopy(declaration)
        self.assertEqual(pp.mixed_roster(declaration)['participants'][0]['hero'], 'Ringo')
        self.assertEqual(declaration, original, 'no hidden composition substitution')
        for i, row in enumerate(declaration['participants'], 1):
            row['hero'] = hero_catalog.resolve_hero_name(roster.BOT_HERO_CHOICES[pp.SLOTS[i]-1][0])
        plan = pp.mixed_roster(declaration)
        assignments = pp.verify_selections(plan, pp.selections(mixed_snapshot(plan)), all_six=True)
        actual = sorted((r['slot'], r['hero_id']) for r in assignments.values() if r['slot'])
        self.assertEqual(actual, list(enumerate((396, 244, 399, 254, 924), 1)))
        declaration['participants'][0]['hero'] = 'Ardan'
        with self.assertRaisesRegex(ValueError, 'measured bot sequence'):
            pp.mixed_roster(declaration)


class TestMixedContracts(unittest.TestCase):
    def setUp(self):
        self.output = pp.new_output()
        self.plan = mixed_declaration()
        self.start = time.time()-1

    def entry(self, **kw):
        return pp.MixedEntry(self.plan, pp.MATCH_ID, self.output/'wire.jsonl', self.start,
                             self.output/'release.json', self.output, **kw)

    def test_clean_one_ce_policy_wiring_preserves_orders_and_records_holds_separately(self):
        from types import SimpleNamespace
        from Tools.protocol_policy import Intent
        entry = self.entry()
        entry.assignments = pp.verify_selections(entry.plan, pp.selections(mixed_snapshot(entry.plan)), all_six=True)
        entry.receipts['world-release'] = {}
        players = [pp.Participant('127.0.0.1', 1, pp.MATCH_ID, r['hero'], self.output,
                                 identity=r['identity'], heartbeat_port=0) for r in entry.plan['participants']]
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        try:
            for p in players:
                assignment = entry.assignments[p.identity]
                p.eid, p.slot, p.team = (assignment[k] for k in ('eid', 'slot', 'team'))
                p.generation = 1
                p.sock = Mock()
            def policy(*args, **kw):
                p = SimpleNamespace(hold={'reason': 'synthetic clean boundary'}, engagement=None)
                def step(actors, now):
                    p.engagement = dict(phase='engagement' if now >= 80 else 'staging')
                    return Intent(1012, roster.build_move(0, -2), 'synthetic ordinary move')
                p.step = step
                return p
            reconnect_times = []
            from server.test.test_protocol_policy import mixed_mesh
            with patch('Tools.protocol_policy.Policy', side_effect=policy) as factory, \
                    patch('server.navigation.load_halcyon_navmesh', return_value=mixed_mesh()), \
                    patch.object(pp.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(pp.time, 'sleep', side_effect=sleep), \
                    patch.object(pp, 'reconnect', side_effect=lambda p: reconnect_times.append(clock[0])) as reconnect:
                result = pp.play_mixed(players, entry, duration=120, reconnect_identity='test-ringo', reconnect_after=75)
            reconnect.assert_called_once_with(players[0])
            self.assertEqual(result['engagement_elapsed_s'], 80)
            self.assertEqual(reconnect_times, [80.5], 'fixed time alone must not reconnect before engagement')
            schedule = json.loads((self.output/'mixed-reconnect-schedule.json').read_text())
            self.assertGreater(schedule['reconnect_elapsed_s'], schedule['engagement_elapsed_s'])
            pair = (entry.assignments['test-skye']['eid'], entry.assignments['test-ringo']['eid'])
            self.assertEqual(len(factory.call_args_list), 5)
            for p, call in zip(players, factory.call_args_list):
                self.assertEqual(call.kwargs['mixed_pair'], pair)
                self.assertEqual(call.kwargs['opponent_eid'], pair[0] if p.identity == 'test-ringo' else None)
            orders = [json.loads(s) for s in (self.output/'mixed-orders.jsonl').read_text().splitlines()]
            holds = [json.loads(s) for s in (self.output/'mixed-holds.jsonl').read_text().splitlines()]
            self.assertTrue(orders and holds)
            self.assertTrue(all(r['opcode'] == 1012 and r['record_index'] for r in orders))
            self.assertTrue(all(r['kind'] == 'mixed-hold' for r in holds))
            for p in players:
                self.assertEqual(result['orders'][p.identity], sum(r['identity'] == p.identity for r in orders))
                self.assertTrue(all(r['match_id'] == pp.MATCH_ID and r['eid'] == p.eid and r['slot'] == p.slot
                                    for r in orders if r['identity'] == p.identity))
        finally:
            for p in players:
                p.log.close()

    def trace(self, snapshot, **changes):
        row = {'time': time.time(), 'direction': 'identity', 'identity': 'test-skye',
               'connection': 17, 'match_id': pp.MATCH_ID, 'eid':1500, 'slot':0, 'team':1}
        row.update(changes)
        frames = [row, {'time':time.time(), 'direction':'s2c', 'connection':17, 'opcode':1113,
                        'payload':snapshot.hex()}]
        (self.output/'wire.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in frames), encoding='utf-8')

    def test_four_and_five_participants_reserve_declared_slots_and_heroes(self):
        for count in (1, 2):
            plan = pp.mixed_roster(mixed_declaration(count))
            bound = pp.verify_selections(plan, pp.selections(mixed_snapshot(plan)), all_six=True, unlocked=True)
            self.assertEqual(len(plan['participants']), 6-count)
            self.assertEqual(bound['test-skye']['slot'], 0)
            self.assertEqual(bound['test-ringo']['team'], 2)
        bad = copy.deepcopy(self.plan)
        bad['participants'][0]['hero'] = 'Skye'
        with self.assertRaisesRegex(ValueError, 'reserved'):
            pp.mixed_roster(bad)
        bad = copy.deepcopy(self.plan)
        bad['real_clients'][0]['slot'] = 3
        with self.assertRaisesRegex(ValueError, 'reserved EID/team'):
            pp.mixed_roster(bad)

    def test_admission_wait_is_read_only_and_requires_identity_and_selection(self):
        self.trace(mixed_snapshot(self.plan, bots=True))
        entry = self.entry(admission_timeout=.05)
        with patch.object(pp.Participant, 'connect') as connect:
            entry.wait_admission()
        connect.assert_not_called()
        self.assertEqual(entry.connections, {'test-skye':17})
        payload = bytearray(mixed_snapshot(self.plan, bots=True))
        struct.pack_into('>H', payload, 8+9, 0xffff)
        self.trace(payload)
        with patch.object(pp.Participant, 'connect') as connect, self.assertRaisesRegex(pp.StageFailure, 'admission timeout'):
            self.entry(admission_timeout=.01).wait_admission()
        connect.assert_not_called()

    def test_admission_rejects_stale_wrong_match_and_prelocked_human(self):
        for kind in ('stale', 'wrong-match', 'locked'):
            with self.subTest(kind=kind):
                payload = bytearray(mixed_snapshot(self.plan, bots=True))
                if kind == 'locked':
                    struct.pack_into('>H', payload, 8+2, roster.PICK_FLAG_LOCKED)
                self.trace(payload, **({'time':self.start-1} if kind == 'stale' else
                                     {'match_id':'wrong'} if kind == 'wrong-match' else {}))
                with self.assertRaises(pp.StageFailure):
                    self.entry(admission_timeout=.01).wait_admission()

    def test_invalid_selection_and_identity_team_pairing_stop_before_lock(self):
        plan = pp.mixed_roster(self.plan)
        rows = pp.selections(mixed_snapshot(plan))
        for change in ({'hero_id':0xffff}, {'identity':'intruder'}, {'team':2}, {'flags':0}):
            bad = copy.deepcopy(rows)
            bad[0].update(change)
            with self.subTest(change=change), self.assertRaises(pp.StageFailure):
                pp.verify_selections(plan, bad, all_six=True)
        # Reordering declarations must not change a binding or pairing.
        plan['participants'].reverse()
        assignments = pp.verify_selections(plan, rows, all_six=True)
        self.assertEqual(assignments['test-amael']['eid'], 1519)
        plan['participants'][0]['opponent'] = 'test-ringo'
        with self.assertRaisesRegex(pp.StageFailure, 'opposing observed team'):
            pp.verify_selections(plan, rows, all_six=True)

    def test_coop_refused_before_connection(self):
        with patch.dict(pp.os.environ, {'HALCYON_TEAM_ALLOCATION':'coop'}), \
                patch.object(pp.Participant, 'connect') as connect, \
                self.assertRaisesRegex(pp.StageFailure, 'default HALCYON_TEAM_ALLOCATION'):
            self.entry()
        connect.assert_not_called()

    def test_reconnect_is_identity_selected_not_index_four(self):
        players = [Mock(identity='one'), Mock(identity='two'), Mock(identity='three')]
        self.assertIs(pp.participant_by_identity(players, 'two'), players[1])
        for identity in ('absent', None):
            with self.assertRaises(pp.StageFailure):
                pp.participant_by_identity(players, identity)

    def test_finalization_wait_requires_ordinary_real_locks_and_respects_bound(self):
        self.trace(mixed_snapshot(self.plan, bots=True))
        entry = self.entry(finalization_timeout=120)
        entry.wait_admission()
        entry.record('draft-ready', {'verified_at':time.time()})
        with self.assertRaisesRegex(pp.StageFailure, '1123/1119'):
            entry.wait_real_locks(time.monotonic()+.01)
        with (self.output/'wire.jsonl').open('a', encoding='utf-8') as trace:
            for direction, opcode in (('c2s',1123), ('s2c',1123), ('c2s',1119)):
                trace.write(json.dumps({'direction':direction, 'opcode':opcode, 'time':time.time(),
                                        'connection':17, 'payload':bytes(6).hex()})+'\n')
        entry.wait_real_locks(time.monotonic()+.1)
        self.assertEqual(entry.finalization_timeout, 120)
        for invalid in (0, -1, float('inf'), float('nan'), 601):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                pp.bounded_seconds(invalid)

    def test_real_lock_after_35_seconds_is_observed_with_configured_wait(self):
        self.trace(mixed_snapshot(self.plan, bots=True))
        entry = self.entry(finalization_timeout=120)
        entry.wait_admission()
        entry.record('draft-ready', {'verified_at':time.time()})
        def arrive(_):
            with entry.trace.open('a', encoding='utf-8') as trace:
                for direction, opcode in (('c2s',1123), ('s2c',1123), ('c2s',1119)):
                    trace.write(json.dumps({'direction':direction, 'opcode':opcode, 'time':time.time(),
                                            'connection':17, 'payload':bytes(6).hex()})+'\n')
        with patch.object(pp.time, 'monotonic', side_effect=[0, 40]), patch.object(pp.time, 'sleep', side_effect=arrive):
            entry.wait_real_locks(120)
        self.assertEqual(set(entry.receipts['real-locks']['test-skye']), {1123,1119,'1123_ack'})

    def test_real_identity_cannot_bind_the_wrong_owner_or_shared_connection(self):
        self.trace(mixed_snapshot(self.plan, bots=True), eid=1517)
        with self.assertRaisesRegex(pp.StageFailure, 'owner differs'):
            self.entry(admission_timeout=.01).wait_admission()
        self.plan = mixed_declaration(2)
        self.trace(mixed_snapshot(self.plan, bots=True))
        with (self.output/'wire.jsonl').open('a', encoding='utf-8') as trace:
            trace.write(json.dumps({'time':time.time(), 'direction':'identity', 'identity':'test-ringo',
                                    'connection':17, 'match_id':pp.MATCH_ID, 'eid':1517, 'slot':3, 'team':2})+'\n')
        with self.assertRaisesRegex(pp.StageFailure, 'distinct observed connections'):
            self.entry(admission_timeout=.01).wait_admission()

    def test_draft_receipt_is_published_atomically_and_partial_trace_is_not_evidence(self):
        entry = self.entry()
        data = {'verified_at':time.time()}
        entry.record('draft-ready', data)
        self.assertEqual(json.loads((self.output/'mixed-draft-ready.json').read_text()), data)
        self.assertFalse((self.output/'mixed-draft-ready.pending').exists())
        complete = json.dumps({'time':time.time(), 'opcode':1113})
        entry.trace.write_text(complete[:-1], encoding='utf-8')
        self.assertEqual(list(entry.trace_rows()), [])
        self.assertEqual(entry.offset, 0)
        with entry.trace.open('a', encoding='utf-8') as stream:
            stream.write(complete[-1:]+'\n')
        self.assertEqual(len(list(entry.trace_rows())), 1)
        entry.trace.write_text('', encoding='utf-8')
        with self.assertRaisesRegex(pp.StageFailure, 'truncated'):
            list(entry.trace_rows())

    def test_world_bootstrap_wait_uses_one_configurable_bound_not_35_seconds(self):
        p = Mock(eid=1517, hero_id=244)
        p.begin.return_value = 9
        p.wait.side_effect = [{'opcode':1011}, {'opcode':1137}, {'opcode':1116}]
        with patch.object(pp.time, 'monotonic', side_effect=[10, 10, 50, 90]):
            pp.ready_participants([p], 120)
        self.assertEqual([call.kwargs['timeout'] for call in p.wait.call_args_list], [120,80,40])
        self.assertEqual([call.args[1] for call in p.input.call_args_list], [1134,1137])

    def test_readiness_serializes_bootstrap_owner_and_never_accepts_another_eid_echo(self):
        owner, peer = Mock(eid=1500, hero_id=265), Mock(eid=1517, hero_id=399)
        events = []
        for p in (owner, peer):
            p.begin.return_value = 0
            p.input.side_effect = lambda stage, op, payload, p=p: events.append((p.eid, op))
            def observe(predicate, *, after, timeout, p=p):
                block = struct.pack('>III', p.hero_id, 0, p.eid)
                if predicate(1011, block):
                    return {'opcode':1011}
                if predicate(1137, roster.build_hero_ready_ack(p.eid)):
                    self.assertFalse(predicate(1137, roster.build_hero_ready_ack(1519)))
                    return {'opcode':1137}
                self.assertTrue(predicate(1116, b''))
                return {'opcode':1116}
            p.wait.side_effect = observe
            p.prove.side_effect = lambda stage, proof, p=p: events.append((p.eid, 'qualified'))
        pp.ready_participants([owner, peer], 120)
        self.assertEqual(events, [(1500,1134),(1500,1137),(1500,'qualified'),
                                  (1517,1134),(1517,1137),(1517,'qualified')])

    def test_unselected_human_at_final_snapshot_stops_without_any_participant_lock(self):
        self.plan = mixed_declaration(evidenced=True)
        entry = self.entry()
        entry.wait_admission = Mock()
        players = []
        valid = mixed_snapshot(self.plan)
        invalid = bytearray(valid)
        struct.pack_into('>H', invalid, 8+9, 0xffff)
        try:
            for i, declaration in enumerate(self.plan['participants'], 1):
                p = pp.Participant('127.0.0.1', 1, pp.MATCH_ID, declaration['hero'], self.output,
                                   identity=declaration['identity'], heartbeat_port=0)
                players.append(p)
                p.eid, p.slot, p.team = pp.EIDS[i], pp.SLOTS[i], 1 if pp.SLOTS[i]<3 else 2
                p.connect, p.input = Mock(), Mock()
                p.wait = Mock(side_effect=[{'opcode':1001, 'payload_hex':struct.pack('>I',p.eid).hex()},
                    {'opcode':1113, 'payload_hex':valid.hex()}, {'opcode':1118},
                    {'opcode':1113, 'payload_hex':invalid.hex()}])
            with self.assertRaisesRegex(pp.StageFailure, 'unselected human'):
                pp.enter_mixed(players, entry)
            for p in players:
                self.assertEqual([call.args[1] for call in p.input.call_args_list], [1118])
        finally:
            for p in players:
                p.close()

    def test_world_release_is_fresh_owner_bound_and_required_for_gameplay(self):
        entry = self.entry(world_timeout=.01)
        entry.assignments = pp.verify_selections(entry.plan, pp.selections(mixed_snapshot(self.plan)), all_six=True)
        entry.connections = {'test-skye':17}
        entry.finalized_at = time.time()-.1
        valid = {'match_id':pp.MATCH_ID, 'qualified_at':time.time(), 'clients':[
            {**entry.assignments['test-skye'], 'connection':17, 'qualified_world':True}]}
        self.assertEqual(entry.verify_release(valid), valid)
        for mutation in ({'eid':1517}, {'connection':18}, {'qualified_world':False}, {'hero_id':244}):
            bad = copy.deepcopy(valid)
            bad['clients'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(pp.StageFailure):
                entry.verify_release(bad)
        for mutation in ({'qualified_at':entry.finalized_at-1}, {'match_id':'other'}, {'clients':[]}):
            with self.subTest(mutation=mutation), self.assertRaises(pp.StageFailure):
                entry.verify_release(valid | mutation)
        with self.assertRaisesRegex(pp.StageFailure, 'release timeout'):
            entry.wait_release([])
        with self.assertRaisesRegex(pp.StageFailure, 'requires a verified'):
            pp.play_mixed([], entry, duration=2, reconnect_identity='test-ringo', reconnect_after=1)
        entry.release.write_text(json.dumps(valid), encoding='utf-8')
        with self.assertRaisesRegex(pp.StageFailure, 'already exists'):
            self.entry()

    def test_mixed_cannot_self_host_or_omit_barriers(self):
        for args in (['--mixed-roster','unused'], ['--mixed-roster','unused','--self-host'],
                     ['--world-release','unused']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                pp.main(args)
            self.assertEqual(error.exception.code, 2)


class TestMixedGatewayFixture(unittest.TestCase):
    def test_one_reserved_wire_standin_and_five_participants_barriers_and_reconnect(self):
        """One extra offline socket fixture; explicitly NOT a CE/native qualification."""
        from Tools.nonvisual_entry import MixedCoordination
        from Tools.scenario_client import TraceTail
        output = pp.new_output()
        print(f'Mixed fixture evidence (wire stand-in, not CE): {output}', flush=True)
        temp = output/'temp'
        temp.mkdir()
        plan = mixed_declaration(evidenced=True)
        players, errors, thread = [], [], None
        with patch.dict(pp.os.environ, {'HALCYON_TRACE_WIRE':'1', 'TEMP':str(temp), 'HALCYON_TEAM_ALLOCATION':'default'}), \
                patch.object(match_server, 'LOCK_COUNTDOWN', .3), \
                patch.object(match_server, 'WORLD_TAPE_PATH', str(output/'no-tape.bin')):
            gw = gateway.Gateway('127.0.0.1', 0, pp.MATCH_ID, heartbeat_port=0, log=lambda _:None)
            gw.start()
            try:
                human = pp.Participant('127.0.0.1', gw.port, pp.MATCH_ID, 'Skye', output,
                                       identity='test-skye', heartbeat_port=gw.relay.port)
                players.append(human)
                before = time.time()
                human.connect()
                human.wait(lambda op,b:op == 1113)
                mark = human.mark()
                selection, commit = pp.draft_payloads([human])[human.identity]
                human.send(1118, selection)
                human.wait(lambda op,b:op == 1118 and b == selection, after=mark)
                trace, = (temp/'halcyon_stack').glob('wire-*.jsonl')
                entry = pp.MixedEntry(plan, pp.MATCH_ID, trace, before, output/'release.json', output,
                                      admission_timeout=10, finalization_timeout=10, world_timeout=10)
                hook = MixedCoordination({'mixed_draft_ready': str(output/'mixed-draft-ready.json'),
                    'mixed_world_release': str(output/'release.json'), 'not_before': before, 'mixed_timeout_s': 10,
                    'mixed_heroes_by_slot': [r['hero'] for i, r in sorted(zip(pp.SLOTS, plan['real_clients']+plan['participants']))]})
                for row in plan['participants']:
                    players.append(pp.Participant('127.0.0.1', gw.port, pp.MATCH_ID, row['hero'], output,
                                   identity=row['identity'], heartbeat_port=gw.relay.port))
                done = threading.Event()
                def enter():
                    try:
                        pp.enter_mixed(players[1:], entry)
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        done.set()
                thread = threading.Thread(target=enter)
                thread.start()
                deadline = time.monotonic()+15
                while not (output/'mixed-draft-ready.json').exists() and not done.is_set() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue((output/'mixed-draft-ready.json').exists(), str(errors))
                self.assertFalse(errors)
                tail = TraceTail(trace)
                tail.poll()
                binding = next(r for r in tail.records if r.get('direction') == 'identity'
                               and r.get('identity') == 'test-skye')
                driver_entry = Mock(d=Mock(tail=tail))
                driver_entry.wait.side_effect = lambda name, predicate, **kw: predicate()
                hook.hold(driver_entry, binding)
                self.assertEqual(json.loads(hook.ready.read_text())['not_before'], before)
                # No lock could have finalized before this ordinary stand-in lock.
                for p in players[1:]:
                    rows = [json.loads(l) for l in pp.Path(p.log.name).read_text().splitlines()]
                    self.assertFalse(any(r['opcode'] in (1134,1137) and r['direction']=='c2s' for r in rows))
                mark = human.mark()
                human.send(1123, bytes(6)); human.send(1119, commit)
                human.wait(lambda op,b:op == 1006, after=mark)
                human.wait(lambda op,b:op == 1132, after=mark)
                human.send(1134, bytes(6)); human.send(1137, roster.build_hero_ready_ack(human.eid))
                human.wait(lambda op,b:op == 1011 and pp.u32(b,8) == human.eid, after=mark)
                human.wait(lambda op,b:op == 1137 and b == roster.build_hero_ready_ack(human.eid), after=mark)
                deadline = time.monotonic()+10
                while entry.finalized_at is None and not done.is_set() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertIsNotNone(entry.finalized_at, str(errors))
                self.assertFalse(done.is_set(), 'participant readiness is not native WORLD release')
                for p in players[1:]:
                    rows = [json.loads(l) for l in pp.Path(p.log.name).read_text().splitlines()]
                    self.assertFalse(any(r['direction']=='c2s' and r['opcode'] in (1134,1137,1012,1060,1078,1081) for r in rows),
                                     'participants must not race the CE native bootstrap/release')
                # Mock qualification only: this fixture has no emulator/native reader.
                hook.publish(binding, {'stage':'QUALIFIED_WORLD', 'at':time.time(), 'eid':human.eid,
                                      'slot':human.slot, 'hero_id':human.hero_id, 'connection':binding['connection']})
                thread.join(15)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual({p.identity:(p.slot,p.team) for p in players[1:]},
                                 {i:(r['slot'],r['team']) for i,r in entry.assignments.items() if i!='test-skye'})
                # The two-second interval below is a gateway/reconnect fixture,
                # not a shortened live-C exercise. Establish its new rendezvous
                # precondition with ordinary wire moves and observed positions;
                # never fake engagement, teleport actors or waive the schedule.
                from Tools.protocol_policy import MixedRendezvous
                from server.navigation import load_halcyon_navmesh
                rendezvous = MixedRendezvous(load_halcyon_navmesh())
                for p in (human, players[1]):
                    rendezvous.route(p.observer.actors[p.eid].position, p.team)
                    p.send(1012, roster.build_move(*rendezvous.point))
                deadline = time.monotonic()+45
                staged = False
                positions = {}
                while time.monotonic() < deadline:
                    # A third socket observes both actors (owner streams may
                    # omit ordinary self-position publications).
                    with players[2].condition:
                        positions = {p.eid: players[2].observer.actors[p.eid].position for p in (human, players[1])}
                    if all(rendezvous.contains(point) for point in positions.values()):
                        staged = True
                        break
                    time.sleep(.05)
                self.assertTrue(staged, f'ordinary fixture staging did not arrive: {positions}')
                result = pp.play_mixed(players[1:], entry, duration=2, reconnect_identity='test-ringo', reconnect_after=.5)
                schedule = json.loads((output/'mixed-reconnect-schedule.json').read_text())
                self.assertGreater(schedule['reconnect_elapsed_s'], schedule['engagement_elapsed_s'])
                self.assertEqual(result['opponents']['test-ringo'], human.eid)
                self.assertEqual(players[1].generation, 2)
                self.assertEqual(players[1].stages['reconnect']['classification'], pp.OBSERVED)
                orders = [json.loads(line) for line in (output/'mixed-orders.jsonl').read_text().splitlines()]
                for p in players[1:]:
                    selected, committed, _ = pp.selection_hashes(p.hero_id)
                    wire_rows = [json.loads(line) for line in pp.Path(p.log.name).read_text().splitlines()]
                    self.assertEqual([r['payload_hex'] for r in wire_rows if r['direction']=='c2s' and r['opcode']==1118],
                                     [(struct.pack('>II', p.hero_id, selected)+bytes(6)).hex()])
                    self.assertEqual([r['payload_hex'] for r in wire_rows if r['direction']=='c2s' and r['opcode']==1119],
                                     [(struct.pack('>I', committed)+bytes(2)).hex()])
                    infos = [bytes.fromhex(r['payload_hex']) for r in wire_rows
                             if r['direction']=='s2c' and r['opcode']==1006
                             and pp.u32(bytes.fromhex(r['payload_hex']),160)==p.eid]
                    self.assertTrue(infos)
                    self.assertTrue(all(pp.u32(info,168)==committed and info[210]==p.team for info in infos))
                    sent = [r for r in orders if r['identity'] == p.identity]
                    staged = [r for name, stage in p.stages.items() if name in ('learn','purchase','move','attack','recall')
                              for r in stage['inputs']]
                    self.assertEqual({r['record_index'] for r in sent}, {r['record_index'] for r in staged})
                    for name in ('learn','purchase','move','attack','recall'):
                        if p.stages[name]['inputs']:
                            self.assertEqual(p.stages[name]['classification'], 'unacknowledged (reason unknown)')
                (output/'summary.json').write_text(json.dumps({'fixture':'wire stand-in, no emulator/native acceptance',
                    'result':result, 'barriers':entry.receipts, 'participants':[p.report() for p in players]}, indent=2), encoding='utf-8')
            finally:
                if thread:
                    thread.join(35)
                for p in players:
                    p.close()
                gw.stop()


class TestBoundaries(unittest.TestCase):
    def test_diagnostic_packet_histories_keep_exact_bounded_tail(self):
        import struct
        from server import wire
        match = match_server.MatchServer(log=lambda _: None)
        conn = Mock()
        conn.getpeername.return_value = ('127.0.0.1', 1)
        count = 1000
        with patch.object(wire, 'read_frame', side_effect=[b'body']*count+[None]), \
                patch.object(match, '_adopt_key'), \
                patch.object(wire, 'decode_body', side_effect=[
                    (wire.OP.KEEPALIVE, struct.pack('>HH2x', wire.KEEPALIVE_MAGIC, tick)) for tick in range(count)]):
            match._handle(conn)
        self.assertEqual(match.keepalive_ticks, list(range(count-256,count)))
        self.assertEqual(match.join_sequence, [(wire.OP.KEEPALIVE,struct.pack('>HH2x',wire.KEEPALIVE_MAGIC,tick))
                                               for tick in range(count-256,count)])

    def test_public_and_non_rfc1918_hosts_refused(self):
        for host in ("8.8.8.8", "1.1.1.1", "169.254.1.1", "100.64.1.1", "0.0.0.0"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                pp.private_host(host)
        for host in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.2"):
            self.assertEqual(pp.private_host(host), host)

    def test_existing_output_refused_including_empty(self):
        output = pp.new_output()
        with self.assertRaises(ValueError):
            pp.new_output(output)
        (output / "retained.txt").write_text("must survive", encoding="utf-8")
        with self.assertRaises(ValueError):
            pp.new_output(output)
        self.assertEqual((output / "retained.txt").read_text(), "must survive")
        with self.assertRaises(ValueError):
            pp.new_output(pp.ROOT / "server/unsafe-evidence")
        with self.assertRaises(ValueError):
            pp.new_output(pp.ROOT.parent / "unsafe-protocol-evidence")

    def test_missing_owned_tape_is_setup_not_gameplay(self):
        parent = pp.new_output()
        output = parent / "missing-input"
        with patch.object(paths, "stack_dir", return_value=parent / "absent-stack"):
            self.assertEqual(pp.main(["--self-host", "--output", str(output)]), 2)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "SETUP")
        self.assertEqual(summary["gameplay_failures"], [])
        self.assertIn(f"missing: {parent / 'absent-stack/world_tape.bin'}", summary["setup_failures"])


class TestParticipants(unittest.TestCase):
    def setUp(self):
        # This six-kit test measures server gameplay/transport, NOT native CE
        # loadout validity. Keep all its original action/reconnect assertions;
        # unavailable Ringo/Gwen hashes are explicitly synthetic fixture data.
        # Production refuses these heroes; the mixed socket fixture above uses
        # only measured hashes and the explicit per-slot bot replacements.
        measured = pp.selection_hashes
        fixture = patch.object(pp, 'selection_hashes', side_effect=lambda hid:
            (0x11223344, 0x55667788, 'synthetic offline wire fixture, not CE evidence')
            if hid in (243, 395) else measured(hid))
        fixture.start()
        self.addCleanup(fixture.stop)
        self.output = pp.new_output()
        self.log_lock = threading.Lock()
        print(f"Participant evidence: {self.output}", flush=True)
        # TEST FIXTURE ONLY: shorten the lock countdown and omit corpus tape.
        # Production navmesh, wall-paced simulation and all gameplay stay intact.
        for name, value in (("LOCK_COUNTDOWN", 0.3),
                            ("WORLD_TAPE_PATH", str(self.output / "no-tape.bin"))):
            override = patch.object(match_server, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.gateway = gateway.Gateway("127.0.0.1", 0, pp.MATCH_ID,
                                       heartbeat_port=0, log=self.log)
        self.gateway.start()
        self.addCleanup(self.gateway.stop)

    def log(self, line):
        with self.log_lock, (self.output / "server.log").open("a", encoding="utf-8") as log:
            log.write(f"{time.time():.6f} {line}\n")

    def test_six_participants_all_actions_and_reconnect(self):
        summary = pp.run("127.0.0.1", self.gateway.port, self.output,
                         heartbeat_port=self.gateway.relay.port, mode="unit-test-no-tape")
        self.assertEqual(summary["status"], "PASS", json.dumps(summary, indent=2))
        self.assertEqual(len({p["identity"] for p in summary["participants"]}), 6)
        for i, participant in enumerate(summary["participants"]):
            self.assertEqual((participant["eid"], participant["slot"], participant["team"]),
                             (pp.EIDS[i], pp.SLOTS[i], 1 if i % 2 == 0 else 2))
            for stage in pp.STAGES[:-1]:
                with self.subTest(hero=participant["hero"], stage=stage):
                    record = participant["stages"][stage]
                    self.assertEqual(record["classification"], pp.OBSERVED)
                    self.assertTrue(record["proving_opcodes"])
            with open(participant["wire_log"], encoding="utf-8") as log:
                rows = [json.loads(line) for line in log]
            self.assertTrue(any(r["lane"] == "heartbeat" and r["direction"] == "c2s" for r in rows))
            self.assertTrue(any(r["opcode"] == 0 and r["direction"] == "c2s" for r in rows))
            self.assertIsNone(participant["receive_error"])
        self.assertEqual(summary["participants"][0]["stages"]["reconnect"]["classification"], pp.OBSERVED)

    def test_cast_before_learning_is_not_accepted(self):
        players = [pp.Participant("127.0.0.1", self.gateway.port, pp.MATCH_ID, hero, self.output,
                                  heartbeat_port=self.gateway.relay.port) for hero in pp.HEROES]
        try:
            pp.enter_world(players)
            p = players[0]
            mark = p.begin("cast")
            op, payload, response = pp.native_cast(p)
            p.input("cast", op, payload)
            with self.assertRaises(pp.StageFailure):
                p.wait(lambda received, body: received == response and pp.u32(body) == p.eid,
                       after=mark, timeout=1.5)
            self.assertIsNone(p.error, "transport failure is not an illegal-action negative control")
            self.assertEqual(p.stages["cast"]["classification"], "unacknowledged (reason unknown)")
            self.assertEqual(p.stages["cast"]["proving_opcodes"], [])
            self.assertFalse(any(op == 1053 and pp.u32(body) == p.eid and body[8] == 2
                                 and pp.struct.unpack_from(">f", body, 4)[0] < 0
                                 for op, body, row in p.messages if row['stream_index'] > mark))
        finally:
            for p in players:
                p.close()
            (self.output / "summary.json").write_text(json.dumps(
                {"mode": "negative-control", "source": pp.source_identity(),
                 "participants": [p.report() for p in players]}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
