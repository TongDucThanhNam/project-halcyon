"""Bounded nonvisual native control receipts shared by the existing driver."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time


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
                  'Lock in a hero!', 'LOCKED IN', 'Choose a Build',
                  'BACKPACK (DRAG TO RE-ORDER)', 'BUY:', 'Settings'}
BLOCKER_MARKERS = {'Settings', 'Choose a Build', 'BACKPACK (DRAG TO RE-ORDER)'}


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
    """Exact ancestry/region except recorded rev4 unclassified leaf flag deltas."""
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
    if (chain_a != chain_b or a['control']['address'] != b['control']['address']
            or any(d['address'] in protected for d in changes)):
        raise ControlMutation(f'{expected_stage}: selected control/full ancestry mutation', changes, ancestry=True)
    target = node_bounds(a['control'])
    # For an offscreen hero, the scroll actually touches its measured list clip.
    # Protect that region too, not just an empty clipped offscreen rectangle.
    if allow_offscreen and not a['visible']:
        target = a['clip']
    outside, tolerated = [], []
    for change in changes:
        x, y = left.get(change['address']), right.get(change['address'])
        if (unclassified_leaf_flags(x, y, change)
                and all(control in ancestor_chain(ns, n['address'], st['root'])[1:]
                        for ns, n, st in ((left, x, before), (right, y, after)))):
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


def screen(state):
    """Stage markers are deliberately narrow; background PLAY can persist."""
    labels = state['labels']
    if labels == ['CONNECTING']:
        return 'BOOTSTRAP'
    if any(s.startswith('Prepare For Battle') or 'Pro Tip:' in s for s in labels):
        return 'LOADING'
    if 'Settings' in labels:
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
