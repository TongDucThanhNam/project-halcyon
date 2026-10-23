"""Bounded nonvisual native control receipts shared by the existing driver."""
from __future__ import annotations

import hashlib
from collections import Counter
import json
import math
from pathlib import Path
import re
import time

from server.hero_catalog import HERO_CATALOG_1107_NAMES, HERO_INTERNAL_ALIASES


def fresh_ui_state(observer, on_gap, *, bracket=False):
    """Retry reads only, never inputs; same bounds as the Classic reader."""
    for attempt in range(20):
        try:
            before = time.monotonic()
            state = observer.ui_state()
            return ({**state, 'host_read_started': before, 'host_read_ended': time.monotonic()}
                    if bracket else state)
        except Exception as exc:
            if not any(s in str(exc) for s in ('native UI cycle/node limit', 'native UI root changed')):
                raise
            on_gap({'at': time.time(), 'attempt': attempt, 'unknown': str(exc)})
            if attempt == 19:
                raise ValueError('native UI tree did not settle; no input attempted') from exc
            time.sleep(.1)


def tree_signature(state):
    return hashlib.sha256(json.dumps({k: state[k] for k in ('root', 'nodes', 'labels')},
                                    sort_keys=True, allow_nan=False).encode()).hexdigest()


SCREEN_MARKERS = {'CONNECTING', 'PLAY', 'SOLO BOTS', '3V3', 'VERY EASY',
                  'Waiting for Players...', 'Lock in a hero!', 'LOCKED IN', 'Choose a Build',
                  'BACKPACK (DRAG TO RE-ORDER)', 'BUY:', 'Settings'}
BLOCKER_MARKERS = {'Settings', 'Choose a Build', 'BACKPACK (DRAG TO RE-ORDER)'}
DRAFT_WAIT_MARKERS = {'SEC', 'Waiting for Players...', 'CAPTAINS', 'JUNGLERS', 'LANERS',
                      'DIFFICULTY', 'LOCK IN', 'Info', 'Skins', 'EXIT MATCH'}
DRAFT_HERO_LABELS = ({name for name in HERO_CATALOG_1107_NAMES if '_Skin_' not in name}
                     | set(HERO_INTERNAL_ALIASES) | {'San Feng'})
# Observed DIFFICULTY value siblings only (not menu difficulty options):
# Local/evidence/run-1791762916290-e5b16631/rev4-entry-review.json links
# rev4 single-entry-01/entry-stages.jsonl /85/before and /175/native;
# rev6 run-1791614100226-840afe49/post-failure-ui.jsonl /0/native;
# step2 run-1791760597244-e13122f5/phase-b/entry/client-result-1791762518.json
# /observations/nonvisual_entry/112/native. Derived node/parent records:
# Local/evidence/run-1791763148710-3e93d183/difficulty-values.json.
DRAFT_DIFFICULTY_VALUES = {'HARD'}


def screen_context(state):
    """Stable screen identifiers and the known modal/root-layer inventory."""
    return {'screen': screen(state), 'labels': sorted(s for s in state['labels']
            if s in SCREEN_MARKERS or s.startswith('Prepare For Battle') or 'Pro Tip:' in s
            or re.fullmatch(r'\d+:\d{2}', s)),
            'blockers': sorted((n['address'], n['text']) for n in state['nodes']
                              if n.get('text') in BLOCKER_MARKERS),
            'root_layers': sorted((n['address'], n['vtable']) for n in state['nodes']
                                  if n.get('parent') == state['root'])}


def complete_tree(state):
    metrics = state.get('traversal', {})
    nodes = {n['address']: n for n in state['nodes']}
    if (metrics.get('complete') is not True or metrics.get('root_unchanged') is not True
            or metrics.get('node_limit') != 4096 or not 0 < metrics.get('visited', 0) < 4096
            or metrics.get('active') != len(state['nodes']) or len(nodes) != len(state['nodes'])
            or state['root'] not in nodes):
        raise ValueError('entry: incomplete/ambiguous native tree; no partial-tree qualification')
    return nodes


def ancestor_chain(nodes, address, root):
    chain = []
    while address != '0x0':
        if address not in nodes or address in chain or len(chain) >= len(nodes):
            raise ValueError('entry: incomplete/cyclic full control ancestry')
        chain.append(address)
        address = nodes[address]['parent']
    if not chain or chain[-1] != root:
        raise ValueError('entry: control ancestry does not reach the qualified root')
    return chain


def tree_differences(before, after):
    left = {n['address']: n for n in before['nodes']}
    right = {n['address']: n for n in after['nodes']}
    changes = []
    for address in sorted(left.keys() | right.keys()):
        a, b = left.get(address), right.get(address)
        if a == b:
            continue
        fields = ({'node': {'before': a, 'after': b}} if a is None or b is None else
                  {key: {'before': a.get(key), 'after': b.get(key)} for key in sorted(a.keys() | b.keys())
                   if key not in a or key not in b or a[key] != b[key]})
        changes.append({'address': address, 'fields': fields})
    return changes


def node_bounds(node):
    """Conservative clipped bounds; unknown shape/size uses its whole clip."""
    clip = node['clip']
    if clip == [-1, -1, -1, -1]:
        clip = [0, 0, 960, 540]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in clip):
        raise ValueError('entry: nonfinite overlap clip')
    box = [max(0, clip[0]), max(0, clip[1]), min(960, clip[2]), min(540, clip[3])]
    size = node.get('resolved_size')
    if size is None and node.get('size_method') == '0xe13e54':
        size = node['size']
    if (size is not None and node.get('bounds_method') == '0xe02010'
            and node.get('local_bounds') == '0xe020b4'):
        values = node['origin'] + node['anchor'] + node['scale'] + size
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError('entry: nonfinite overlap bounds')
        lo = [node['origin'][i]-node['anchor'][i]*node['scale'][i]*size[i] for i in range(2)]
        hi = [lo[i]+node['scale'][i]*size[i] for i in range(2)]
        # Native e02010 rounds the resulting corners. Expand by half a pixel
        # here rather than wrongly excluding a rounding-edge overlap.
        box = [max(box[0], min(lo[0], hi[0])-.5), max(box[1], min(lo[1], hi[1])-.5),
               min(box[2], max(lo[0], hi[0])+.5), min(box[3], max(lo[1], hi[1])+.5)]
    return box


class ControlMutation(ValueError):
    def __init__(self, detail, differences, *, ancestry=False, settling=False, replan=False):
        super().__init__(detail)
        self.differences, self.ancestry = differences, ancestry
        self.settling = ancestry or settling
        self.replan = replan


def unclassified_leaf_flags(a, b, change):
    """Rev4 structural exception; flag meanings and leaf hit-testing are unknown."""
    return (a is not None and b is not None and set(change['fields']) == {'flags'}
            and all(n.get('child') == '0x0' and not n.get('text') and n.get('events') == []
                    and isinstance(n.get('flags'), int) and not n['flags'] & 16 for n in (a, b))
            and a['flags'] & 0x1C == b['flags'] & 0x1C
            and {k: v for k, v in a.items() if k != 'flags'}
                == {k: v for k, v in b.items() if k != 'flags'})


def qualify_pair(before, after, label, expected_stage, *, hero_id=None, allow_offscreen=False):
    """Exact protected region except recorded leaf deltas and isolated 0x2 pulses."""
    left, right = complete_tree(before), complete_tree(after)
    changes = tree_differences(before, after)
    if before['root'] != after['root'] or screen_context(before) != screen_context(after):
        raise ControlMutation(f'{expected_stage}: root/screen/blocker mutation between reads', changes)
    a = control_receipt(before, label, expected_stage, hero_id=hero_id, allow_offscreen=allow_offscreen)
    control = a['control']['address']
    # These are no-input qualification reads, including final pre-tap reads.
    # Check before resolving the second label: a descendant losing active bits
    # must not be misclassified as an ordinary missing-label setup failure.
    for change in changes:
        x, y = left.get(change['address']), right.get(change['address'])
        if x is not None and y is not None and (x['flags'] ^ y['flags']) & 0x1C:
            if any(control in ancestor_chain(ns, n['address'], st['root'])[1:]
                   for ns, n, st in ((left, x, before), (right, y, after))):
                raise ControlMutation(f'{expected_stage}: REPLAN descendant flags & 0x1C changed without input',
                                      changes, replan=True)
    b = control_receipt(after, label, expected_stage, hero_id=hero_id, allow_offscreen=allow_offscreen)
    chain_a = ancestor_chain(left, a['label_widget'], before['root'])
    chain_b = ancestor_chain(right, b['label_widget'], after['root'])
    protected = set(chain_a) | set(chain_b)
    # 069fa697 gate: 541 pairs, 118 xor-2 edges; 21 geometry-coincident
    # edges refused. Six geometry-free episodes have >=1s follow-up without
    # motion (two censored). Non-tolerated protected changes still refuse pulses:
    # 11 eligible pairs / 77 edges, not every geometry-free pair. No reversal
    # prerequisite: final revalidation may be the last retained read.
    leaf_addresses = {d['address'] for d in changes
        if unclassified_leaf_flags(left.get(d['address']), right.get(d['address']), d)
        and all(control in ancestor_chain(ns, d['address'], st['root'])[1:]
                for ns, st in ((left, before), (right, after)))}
    pulse_addresses, protected_changes = set(), []
    for change in changes:
        address = change['address']
        regions = []
        for nodes, state, receipt, chain in ((left, before, a, chain_a), (right, after, b, chain_b)):
            node = nodes.get(address)
            if node is None:
                continue
            target = node_bounds(receipt['control']) if receipt['visible'] else receipt['clip']
            rect = node_bounds(node)
            region = ('control' if address == receipt['control']['address'] else
                      'ancestry' if address in chain else
                      'subtree' if receipt['control']['address'] in ancestor_chain(nodes, address, state['root']) else
                      'overlap' if max(rect[0], target[0]) < min(rect[2], target[2]) and
                                   max(rect[1], target[1]) < min(rect[3], target[3]) else None)
            if region:
                regions.append(region)
        if regions:
            protected_changes.append(change)
            flags = change['fields'].get('flags', {})
            if (set(regions) <= {'ancestry', 'overlap'} and set(change['fields']) == {'flags'}
                    and isinstance(flags.get('before'), int) and isinstance(flags.get('after'), int)
                    and flags['before'] ^ flags['after'] == 2):
                pulse_addresses.add(address)
    if any(d['address'] not in pulse_addresses | leaf_addresses for d in protected_changes):
        pulse_addresses.clear()
    if (chain_a != chain_b or a['control']['address'] != b['control']['address']
            or any(d['address'] in protected - pulse_addresses for d in changes)):
        raise ControlMutation(f'{expected_stage}: selected control/full ancestry mutation', changes, ancestry=True)
    target = node_bounds(a['control'])
    # For an offscreen hero, the scroll actually touches its measured list clip.
    # Protect that region too, not just an empty clipped offscreen rectangle.
    if allow_offscreen and not a['visible']:
        target = a['clip']
    outside, tolerated = [], []
    for change in changes:
        if change['address'] in pulse_addresses:
            tolerated.append({**change, 'classification': 'PULSE_0x2', 'xor': 2, 'changed_bits': [1]})
            continue
        x, y = left.get(change['address']), right.get(change['address'])
        if change['address'] in leaf_addresses:
            xor = x['flags'] ^ y['flags']
            tolerated.append({**change, 'classification': 'UNCLASSIFIED', 'xor': xor,
                              'changed_bits': [bit for bit in range(xor.bit_length()) if xor & (1 << bit)]})
            continue
        for nodes, state in ((left, before), (right, after)):
            node = nodes.get(change['address'])
            if node is None:
                continue
            chain = ancestor_chain(nodes, node['address'], state['root'])
            if control in chain:
                raise ControlMutation(f'{expected_stage}: selected control descendant mutation', changes, settling=True)
            rect = node_bounds(node)
            if max(rect[0], target[0]) < min(rect[2], target[2]) and max(rect[1], target[1]) < min(rect[3], target[3]):
                raise ControlMutation(f'{expected_stage}: overlapping native node mutation', changes, settling=True)
        outside.append(change)
    b.update(ancestors=chain_b, pair={'before_sha256': tree_signature(before),
        'after_sha256': tree_signature(after), 'screen_context': screen_context(after),
        'outside_difference_count': len(outside), 'outside_differences': outside,
        'tolerated_difference_count': len(tolerated), 'tolerated_differences': tolerated,
        'traversals': [before['traversal'], after['traversal']]})
    return b


def draft_roster_labels(state, labels, handles):
    """Read-only, wire-counted names in the retained CE roster-card branch.

    Structure: run-1791763148710-3e93d183/phase-c/ancestry.json.
    Text -> card -> shared list -> pane -> roster -> content -> marker LCA.
    No absolute address, handle spelling or global roster is trusted.
    """
    if not handles or any(type(handles.get(s)) is not int or
                          count > handles[s] for s, count in Counter(labels).items()):
        return False
    try:
        nodes = {n['address']: n for n in state['nodes']}
        if len(nodes) != len(state['nodes']):
            return False
        markers = [[n for n in nodes.values() if n.get('text') == s] for s in DRAFT_WAIT_MARKERS]
        if any(len(group) != 1 for group in markers):
            return False
        chains = [ancestor_chain(nodes, group[0]['address'], state['root']) for group in markers]
        lca = next(a for a in chains[0] if all(a in chain for chain in chains))
        difficulty = next(group[0]['parent'] for group in markers if group[0]['text'] == 'DIFFICULTY')
        names = [n for n in nodes.values() if n.get('text') in labels]
        if Counter(n['text'] for n in names) != Counter(labels):
            return False
        lists, cards = set(), set()
        for node in names:
            chain = ancestor_chain(nodes, node['address'], state['root'])
            if (len(chain) < 7 or chain[6] != lca or difficulty in chain
                    or [nodes[a].get('vtable') for a in chain[:7]] !=
                       ['0x2726530', '0x26fa2d0', '0x27284a0', '0x27284a0',
                        '0x26d27e0', '0x27266f0', '0x27260b8']
                    or any(chain[2] in c for c in chains) or chain[1] in cards):
                return False
            lists.add(chain[2])
            cards.add(chain[1])
        return len(lists) == 1
    except (KeyError, ValueError, StopIteration):
        return False


def screen(state, *, roster_handles=None):
    """Stage markers are deliberately narrow; background PLAY can persist."""
    labels = state['labels']
    if labels == ['CONNECTING']:
        return 'BOOTSTRAP'
    if any(s.startswith('Prepare For Battle') or 'Pro Tip:' in s for s in labels):
        return 'LOADING'
    if 'Settings' in labels:
        return 'UNKNOWN'
    # Rev6 retained complete tree after identity-bound 1001/1108/1113:
    # waiting roster -> five later ordinary DRAFT reads, with no intervening
    # input. This is only a bounded read-only transition, never a draft control.
    if 'Waiting for Players...' in labels:
        if not all(labels.count(s) == 1 for s in DRAFT_WAIT_MARKERS):
            return 'UNKNOWN'
        extra = [s for s in labels if s not in DRAFT_WAIT_MARKERS | DRAFT_HERO_LABELS]
        if not extra:
            return 'DRAFT_WAIT'
        if roster_handles is not None:
            names = [s for s in extra if s not in DRAFT_DIFFICULTY_VALUES]
            if names:
                if not draft_roster_labels(state, names, roster_handles):
                    return 'UNKNOWN'
                extra = [s for s in extra if s in DRAFT_DIFFICULTY_VALUES]
                if not extra:
                    return 'DRAFT_WAIT'
        # Preserve label-only callers; the exception needs an unambiguous
        # direct sibling in the node tree, never a global label allowance.
        if len(extra) == 1 and extra[0] in DRAFT_DIFFICULTY_VALUES:
            nodes = state.get('nodes', [])
            markers = [n for n in nodes if n.get('text') == 'DIFFICULTY']
            values = [n for n in nodes if n.get('text') == extra[0]]
            if len(markers) == len(values) == 1:
                parent = markers[0].get('parent')
                if (parent and parent != '0x0' and values[0].get('parent') == parent
                        and any(n.get('address') == parent for n in nodes)):
                    return 'DRAFT_WAIT'
        return 'UNKNOWN'
    # Two complete live post-VERY-EASY reads (2026-10-10) show these retiring
    # mode cards while the accepted join attaches draft. This is not MENU and
    # never permits PLAY; only the server-bound draft transition may await it.
    if sorted(labels) == sorted(['Guest', 'PLAY', 'BAG', 'PLAY', '5V5', '25 MIN', 'BLITZ', '5 MIN']):
        return 'MENU_TRANSITION'
    for marker, stage in (('Choose a Build', 'BUILD'), ('BACKPACK (DRAG TO RE-ORDER)', 'SHOP'),
                          ('LOCKED IN', 'LOCKED'), ('Lock in a hero!', 'DRAFT'),
                          ('VERY EASY', 'DIFFICULTY'), ('SOLO BOTS', 'MODE'), ('3V3', 'MAP')):
        if marker in labels:
            return stage
    if 'BUY:' in labels and any(re.fullmatch(r'\d+:\d{2}', s) for s in labels):
        return 'HUD'
    if labels.count('PLAY') == 1:
        return 'MENU'
    return 'UNKNOWN'


def control_receipt(state, label, expected_stage, *, hero_id=None, allow_offscreen=False):
    """Unique active text -> click ancestor -> code-qualified clipped rectangle."""
    if screen(state) == 'DRAFT_WAIT':
        raise ValueError('DRAFT_WAIT: read-only transition; no control receipt')
    if screen(state) != expected_stage:
        raise ValueError(f'{expected_stage}: unexpected native screen {screen(state)}')
    age = time.monotonic() - state['host_read_started']
    if not 0 <= age <= 1.5:
        raise ValueError(f'{expected_stage}: stale native label receipt ({age:.3f}s)')
    nodes = {n['address']: n for n in state['nodes']}
    matches = [n for n in state['nodes'] if n.get('text') == label and n['flags'] & 12 == 12]
    if len(matches) != 1:
        raise ValueError(f'{expected_stage}: label {label!r} absent or duplicate')
    node = matches[0]
    ancestors = []
    for _ in range(12):
        if node['flags'] & 12 != 12 or node['address'] in ancestors:
            raise ValueError(f'{expected_stage}: inactive/cyclic control ancestor')
        ancestors.append(node['address'])
        clicks = [e for e in node['events'] if e['type'] == 10712282]
        if clicks:
            break
        node = nodes.get(node['parent'])
        if node is None:
            raise ValueError(f'{expected_stage}: click-event ancestor absent')
    else:
        raise ValueError(f'{expected_stage}: click-event ancestor depth bound')
    if node['flags'] & 16 == 0:
        raise ValueError(f'{expected_stage}: click control not enabled for input')
    # Ordinary buttons also carry an internal click handler (retained OPEN
    # SHOP has two). Uniqueness applies to the active control, not listener count.
    if hero_id is not None and (node['vtable'] != '0x26d2928'
            or sum(int(e['words'][4], 16) == hero_id for e in clicks) != 1):
        raise ValueError(f'{expected_stage}: hero callback/identity mismatch')
    if (node['bounds_method'], node['local_bounds'], node['size_method']) != ('0xe02010', '0xe020b4', '0xe13e54'):
        raise ValueError(f'{expected_stage}: native rectangle methods unqualified')
    values = node['origin'] + node['anchor'] + node['scale'] + node['size'] + node['clip']
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in values):
        raise ValueError(f'{expected_stage}: nonfinite control bounds')
    if any(v <= 0 for v in node['scale'] + node['size']):
        raise ValueError(f'{expected_stage}: empty control bounds')
    lo = [node['origin'][i] - node['anchor'][i]*node['scale'][i]*node['size'][i] for i in range(2)]
    hi = [lo[i] + node['scale'][i]*node['size'][i] for i in range(2)]
    center = [round((lo[i]+hi[i])/2) for i in range(2)]
    clip = [max(0, node['clip'][0]), max(0, node['clip'][1]),
            min(960, node['clip'][2]), min(540, node['clip'][3])]
    if clip[0] >= clip[2] or clip[1] >= clip[3]:
        raise ValueError(f'{expected_stage}: clip outside viewport')
    visible = all(max(lo[i], clip[i]) < center[i] < min(hi[i], clip[i+2]) for i in range(2))
    if not visible and not allow_offscreen:
        raise ValueError(f'{expected_stage}: clipped/offscreen control {label!r}')
    return {'stage': expected_stage, 'label': label, 'hero_id': hero_id, 'root': state['root'],
            'label_widget': matches[0]['address'], 'control': node, 'ancestors': ancestors,
            'center': center, 'clip': clip, 'visible': visible,
            'tree_sha256': tree_signature(state), 'host_read_started': state['host_read_started']}


def protected_signature(state, label, expected_stage, *, hero_id=None, allow_offscreen=False,
                        include_pulse_nodes=False):
    """Historical structure only: no timestamp checks and never an input receipt.

    Same protected set/hash as ba0ea6b2's measure_protected.py: label ancestry,
    selected control subtree, overlapping nodes, root/context and target bounds.
    Resolve geometry independently so receipt freshness/semantics stay untouched.
    """
    nodes = complete_tree(state)
    if screen(state) != expected_stage or screen(state) == 'DRAFT_WAIT':
        raise ValueError(f'{expected_stage}: unexpected structural screen {screen(state)}')
    matches = [n for n in state['nodes'] if n.get('text') == label and n['flags'] & 12 == 12]
    if len(matches) != 1:
        raise ValueError(f'{expected_stage}: label {label!r} absent or duplicate')
    node = matches[0]
    ancestors = []
    for _ in range(12):
        if node['flags'] & 12 != 12 or node['address'] in ancestors:
            raise ValueError(f'{expected_stage}: inactive/cyclic control ancestor')
        ancestors.append(node['address'])
        clicks = [e for e in node['events'] if e['type'] == 10712282]
        if clicks:
            break
        node = nodes.get(node['parent'])
        if node is None:
            raise ValueError(f'{expected_stage}: click-event ancestor absent')
    else:
        raise ValueError(f'{expected_stage}: click-event ancestor depth bound')
    if node['flags'] & 16 == 0:
        raise ValueError(f'{expected_stage}: click control not enabled for input')
    if hero_id is not None and (node['vtable'] != '0x26d2928'
            or sum(int(e['words'][4], 16) == hero_id for e in clicks) != 1):
        raise ValueError(f'{expected_stage}: hero callback/identity mismatch')
    if (node['bounds_method'], node['local_bounds'], node['size_method']) != ('0xe02010', '0xe020b4', '0xe13e54'):
        raise ValueError(f'{expected_stage}: native rectangle methods unqualified')
    values = node['origin'] + node['anchor'] + node['scale'] + node['size'] + node['clip']
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in values):
        raise ValueError(f'{expected_stage}: nonfinite control bounds')
    if any(v <= 0 for v in node['scale'] + node['size']):
        raise ValueError(f'{expected_stage}: empty control bounds')
    lo = [node['origin'][i] - node['anchor'][i]*node['scale'][i]*node['size'][i] for i in range(2)]
    hi = [lo[i] + node['scale'][i]*node['size'][i] for i in range(2)]
    center = [round((lo[i]+hi[i])/2) for i in range(2)]
    clip = [max(0, node['clip'][0]), max(0, node['clip'][1]),
            min(960, node['clip'][2]), min(540, node['clip'][3])]
    if clip[0] >= clip[2] or clip[1] >= clip[3]:
        raise ValueError(f'{expected_stage}: clip outside viewport')
    visible = all(max(lo[i], clip[i]) < center[i] < min(hi[i], clip[i+2]) for i in range(2))
    if not visible and not allow_offscreen:
        raise ValueError(f'{expected_stage}: clipped/offscreen control {label!r}')
    target = node_bounds(node) if visible else clip
    addresses = set(ancestor_chain(nodes, matches[0]['address'], state['root']))
    pulse_maskable = addresses - {node['address']}
    leaf_maskable = set()
    for address, candidate in nodes.items():
        rect = node_bounds(candidate)
        chain = ancestor_chain(nodes, address, state['root'])
        subtree = node['address'] in chain
        # Canonicalize only the equivalence already accepted by qualify_pair:
        # the identical rev4 predicate, on a strict control descendant. Keep
        # every other field and all 0x1C bits in the structural signature.
        canonical = {**candidate, 'flags': candidate['flags'] & 0x1C}
        if (node['address'] in chain[1:] and unclassified_leaf_flags(candidate, canonical,
                {'fields': {'flags': {'before': candidate['flags'], 'after': canonical['flags']}}})):
            leaf_maskable.add(address)
        overlap = (
                max(rect[0], target[0]) < min(rect[2], target[2]) and
                max(rect[1], target[1]) < min(rect[3], target[3]))
        if subtree or overlap:
            addresses.add(address)
        if overlap and not subtree:
            pulse_maskable.add(address)
    value = {'root': state['root'], 'context': screen_context(state),
             'nodes': [{**nodes[a], 'flags': nodes[a]['flags'] & 0x1C} if a in leaf_maskable else
                       {**nodes[a], 'flags': nodes[a]['flags'] & ~2} if a in pulse_maskable else nodes[a]
                       for a in sorted(addresses)], 'target': target}
    signature = hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return (signature, pulse_maskable) if include_pulse_nodes else signature


def require_unchanged(receipt, state):
    if time.monotonic() - receipt['host_read_started'] > 1.5:
        raise ValueError(f"{receipt['stage']}: stale control before input")
    if tree_signature(state) != receipt['tree_sha256']:
        raise ValueError(f"{receipt['stage']}: native tree mutation between read and input")


class ClientInputState:
    """Compile the read-only Java adapter using an explicit external dependency.

    The bundle and source digest stay with external evidence. No downloaded
    dependency, executable or owned client payload is added to the repository.
    """
    def __init__(self, observer, output, bridge):
        self.observer, self.output, self.bridge = observer, Path(output), Path(bridge)
        self.script = None

    def start(self):
        import frida
        package = json.loads((self.bridge / 'package.json').read_text(encoding='utf-8'))
        if package.get('name') != 'frida-java-bridge' or package.get('version') != '7.0.13':
            raise ValueError('Java view adapter requires retained frida-java-bridge 7.0.13')
        source = Path(__file__).with_name('Teardown') / 'client_input_state.js'
        entry = self.output / 'client-input-state.js'
        entry.write_text(source.read_text(encoding='utf-8').replace("'frida-java-bridge'",
                         json.dumps((self.bridge / 'index.js').resolve().as_posix())), encoding='utf-8')
        bundle = frida.Compiler().build(str(entry), project_root=str(self.output))
        (self.output / 'client-input-state.bundle.js').write_text(bundle, encoding='utf-8')
        self.script = self.observer.session.create_script(bundle)
        self.script.load()
        return {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'bundle_sha256': hashlib.sha256(bundle.encode()).hexdigest(), 'bridge_version': package['version']}

    def snapshot(self):
        return self.script.exports_sync.snapshot()

    def stop(self):
        if self.script is not None:
            self.script.unload()
            self.script = None
