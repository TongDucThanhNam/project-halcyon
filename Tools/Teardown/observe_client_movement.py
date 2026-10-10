"""Read-only client position/correction observer for the pinned owned ARM64 CE.

Uses Frida's native realm to READ mapped data, not to call/hook translated ARM.
The registry/accessors derive from 1070's identified consumer. An already-owned
Frida endpoint is required; this module does not install/start daemons or drive UI.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import threading
import time

BINARY_SHA256 = 'cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47'
from server.paths import local_root
DEFAULT_LIBRARY = local_root() / 'vainglory/lib/arm64-v8a/libGameKindred.so'
ANCHORS = ((0x8284bc, 0x70), (0xc9e390, 0xac), (0xc55794, 0x30), (0xc05af8, 0xf8),
           # UI root, active-child traversal, text storage and UTF-16 copy.
           (0xe0061c, 0xc), (0xe02710, 0xa4), (0xe0d3a4, 0x50), (0x810394, 0x60),
           # 1053/1054 resource consumer and native HP/energy clamping.
           (0x82a024, 0x70), (0xc04408, 0x90), (0xc01624, 0x250),
           (0xcaa5a0, 0xb4), (0xc5f6b0, 0x44), (0xc5f754, 0x60), (0xc5f840, 0x6c),
           # Default-item HUD binding, touch callback and rectangular layout.
           (0x9300f8, 0x370), (0x9305c8, 8), (0x930f2c, 0x100),
           (0xe02010, 0x100), (0xe13e54, 8),
           # HUD scalar kill/death/assist/farm attribute consumers.
           (0x957c98, 0x210),
           # Saved camera-lock preference, input owner and ordinary lock button.
           (0x8f1f64, 0x30), (0x9114dc, 12), (0x9150e4, 0x6c),
           (0x93b354, 0x64), (0x9170cc, 0x40),
           # Ability HUD owner/action binding and ordinary upgrade callback.
           (0x923dd8, 0x70), (0x924160, 0x50), (0x922ed0, 8),
           (0x927d68, 0x30), (0x9287e4, 0xbc),
           # Utilities item 0 -> Recall input for the current owner.
           (0x96eb98, 8), (0x96ff1c, 0xd4), (0x8c7a54, 0x1a0),
           (0x919ed0, 0x14), (0x91704c, 0x50),
           # Utilities item 2 -> native shop panel.
           (0x919fa4, 0x14), (0x8c5278, 0x6c), (0x8c3c1c, 0x88),
           # Shop row item ID, owner binding and ordinary selection callback.
           (0x960b70, 0xc0), (0x96307c, 12), (0x965914, 12), (0x965588, 0xfc),
           # 1085 owner -> inventory slots -> item/instance/quantity accessors.
           (0xc03188, 0x80), (0xc5c5c4, 0x30), (0xc72a18, 0x194),
           (0xc70fc4, 0x38), (0xc71740, 0x2c), (0xc73a9c, 0x7c),
           # Ordinary BUY event and detail owner/selection/mode bindings.
           (0x95c4a8, 0x70), (0x95c7b0, 0x5c), (0x95a9f4, 0x26c),
           # Entity -> presentation interface -> owned model matrix, mesh binding.
           (0xc58004, 0xa0), (0x8ad524, 0x10), (0x8a8720, 0x64),
           (0x8a9d6c, 0x1c0), (0xd7cce0, 0x90), (0xd7ccd0, 8),
           (0x188ac08, 0x2c), (0x8b2364, 0x74),
           # Active camera binding, native screen/world consumers and viewport.
           (0x81ef04, 0x90), (0x81ef94, 0x90), (0x8bbfb0, 12), (0x8bd5c8, 8),
           (0x8b87f0, 0x12c), (0x8b891c, 0x218), (0xe00238, 0x18), (0xe034d4, 0x14),
           # Native ordinary entity picking uses this bounded selection capsule.
           (0xc5b4e0, 0x78), (0xc9e458, 0x120),
           # Re-selecting the same native target does not resend1060.
           (0x9153f0, 0x178), (0x885090, 0x28), (0x826ba0, 0x60),
           # Bounded navigation query and its 3D path cursor consumer.
           (0xc60ff4, 0x9c), (0xc60208, 0x1fc),
           # Native movement speed: attribute18 plus typed directional modifiers.
           (0xc9ee8c, 0xb8), (0xc772c8, 0x334),
           (0xdf09b4, 0x40), (0xdf09f8, 0x100), (0xdf0f78, 0x1fc))


def mapped_base(maps):
    bases = set()
    for line in maps.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[-1].endswith('/lib/arm64/libGameKindred.so') and int(parts[2], 16) == 0:
            bases.add(int(parts[0].split('-')[0], 16))
    if len(bases) != 1:
        raise ValueError('expected exactly one mapped ARM64 Kindred image with offset zero')
    return next(iter(bases))


MENU_ANCHORS = ((0xe0e700, 0x4c), (0xe13458, 0x34), (0xe0d4e0, 0x68),
                (0xe09b18, 0x60), (0xe08d20, 8), (0xe01c10, 0x10))


def anchor_config(library, *, ui_only=False):
    data = Path(library).read_bytes()
    if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
        raise ValueError('movement anchors require the pinned owned ARM64 library')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * size) for i in range(count)]
    anchors = []
    for va, length in ANCHORS + (MENU_ANCHORS if ui_only else ()):
        segment = next(s for s in segments if s[0] == 1 and s[3] <= va and va + length <= s[3] + s[5])
        offset = segment[2] + va - segment[3]
        anchors.append({'va': va, 'bytes': list(data[offset:offset + length])})
    return anchors


class ClientMovementObserver:
    def __init__(self, adb, output, eid, *, endpoint='127.0.0.1:27042', library=DEFAULT_LIBRARY,
                 period_ms=10, model_transform=False, ui_only=False):
        if not 5 <= period_ms <= 100:
            raise ValueError('sampling period must be 5..100 ms')
        self.adb, self.output, self.eid = adb, Path(output), eid
        self.endpoint, self.library, self.period_ms = endpoint, library, period_ms
        if type(model_transform) is not bool:
            raise ValueError('model_transform must be a boolean')
        self.model_transform = model_transform
        if type(ui_only) is not bool:
            raise ValueError('ui_only must be a boolean')
        if ui_only and (eid is not None or model_transform):
            raise ValueError('UI-only observer cannot claim a gameplay owner/model')
        self.ui_only = ui_only
        self.session = self.script = self.handle = None
        self.errors, self.clocks = [], []
        self.lock = threading.Lock()
        self.samples = 0
        self.metadata = {}

    def _message(self, message, _data):
        with self.lock:
            if message.get('type') == 'send':
                payload = message['payload']
                if 'error' in payload:
                    self.errors.append(payload['error'])
                for sample in payload.get('samples', []):
                    self.handle.write(json.dumps(sample, separators=(',', ':')) + '\n')
                    self.samples += 1
                self.handle.flush()
            else:
                self.errors.append(message)

    def calibrate(self):
        measurements = []
        for _ in range(7):
            before, before_wall = time.monotonic(), time.time()
            sample = self.script.exports_sync.snapshot()
            after = time.monotonic()
            measurements.append({'host_monotonic_before_s': before, 'host_monotonic_after_s': after,
                                 'host_wall_before_s': before_wall, 'client': sample})
        # Preserve ALL brackets; consumers can choose the narrowest and assess
        # drift. Guest wall clock is not presumed aligned with the host.
        self.clocks.append(measurements)
        return min(measurements, key=lambda m: m['host_monotonic_after_s'] - m['host_monotonic_before_s'])

    def ui_state(self):
        """Code-anchored active native labels; never pixels or guessed panels."""
        return self.script.exports_sync.ui_state()

    def resources(self):
        """Bounded native current/max resources, separate from movement sampling."""
        return self.script.exports_sync.resources()

    def movement_modifiers(self):
        """Code-anchored bounded component reads; not a native function call."""
        return self.script.exports_sync.movement_modifiers()

    def snapshot(self):
        """One qualified native logical-position/correction read."""
        return self.script.exports_sync.snapshot()

    def default_item_control(self, instance_id):
        """Read a default item's owner-bound native touch rectangle; no input."""
        return self.script.exports_sync.default_item_control(instance_id)

    def camera_control(self):
        """Saved lock preference and code-identified ordinary HUD toggle."""
        return self.script.exports_sync.camera_control()

    def camera_view(self):
        """Qualified active view/projection matrices, not an image/frame read."""
        return self.script.exports_sync.camera_view()

    def actor_states(self, eids):
        """Read explicitly requested actors from the qualified typed registry."""
        return self.script.exports_sync.actor_states(list(eids))

    def selected_target(self):
        """Owner's generation-qualified native selection, not server aggro."""
        return self.script.exports_sync.selected_target()

    def native_path(self):
        """Read the owner's bounded native steering path; no native query call."""
        return self.script.exports_sync.native_path()

    def project_position(self, position_xyz):
        """Project a supplied world point using fresh, read-only native matrices."""
        from .client_projection import world_to_screen
        camera = self.camera_view()
        return {'camera': camera, 'world_xyz': list(position_xyz),
                'screen_xy': world_to_screen(camera, position_xyz)}

    def ability_control(self, slot, *, upgrade=False):
        """Owner/lifetime-bound native cast or upgrade rectangle, without input."""
        return self.script.exports_sync.ability_control(slot, upgrade)

    def recall_control(self):
        """Code-bound utilities item zero -> ordinary owner Recall input."""
        return self.script.exports_sync.recall_control()

    def shop_control(self):
        """Code-bound utilities item two -> ordinary shop panel input."""
        return self.script.exports_sync.shop_control()

    def shop_item_control(self, item_id):
        """Owner-bound visible native catalog row for a numeric item ID."""
        return self.script.exports_sync.shop_item_control(item_id)

    def inventory(self):
        """Bounded native owner inventory, independent of server state/UI labels."""
        return self.script.exports_sync.inventory()

    def shop_buy_control(self, item_id):
        """Native BUY button qualified against owner, selected item and mode."""
        return self.script.exports_sync.shop_buy_control(item_id)

    def start(self):
        import frida
        pid_text = self.adb.shell('pidof com.superevilmegacorp.game')
        if not pid_text.isdecimal():
            raise ValueError('owned client PID absent or ambiguous')
        pid = int(pid_text)
        maps = self.adb.shell(f"su -c 'cat /proc/{pid}/maps'")
        base = mapped_base(maps)
        config = {'eid': self.eid, 'base': hex(base), 'period_ms': self.period_ms,
                  'ui_only': self.ui_only,
                  'model_transform': self.model_transform,
                  'anchors': anchor_config(self.library, ui_only=self.ui_only)}
        source = Path(__file__).with_name('client_movement_observer.js').read_text(encoding='utf-8')
        source = source.replace('__CONFIG__', json.dumps(config))
        self.handle = self.output.open('x', encoding='utf-8')
        try:
            device = frida.get_device_manager().add_remote_device(self.endpoint)
            self.session = device.attach(pid, realm='native')
            self.script = self.session.create_script(source)
            self.script.on('message', self._message)
            self.script.load()
            self.metadata = {'pid': pid, 'library_sha256': BINARY_SHA256, 'period_ms': self.period_ms,
                             **self.script.exports_sync.qualify(), 'source': '1070 consumer -> entity registry -> position accessor',
                             'limit': 'Logical client entity position and correction state; not a rendered/model transform.'}
            if self.model_transform:
                self.metadata.update(model_transform=True,
                    model_source='c58004 -> owner presentation interface -> 8ad524 -> d7cce0 model matrix',
                    limit='Logical entity plus owner-bound root model world matrix. Not bone pose, camera projection, or display-time/frame measurement.')
            if self.ui_only:
                self.metadata.update(source='code-anchored native UI root and active controls',
                                     limit='UI only; no gameplay owner or WORLD qualification.')
            else:
                self.calibrate()
                self.script.exports_sync.start()
            return self.metadata
        except Exception:
            self.stop()
            raise

    def stop(self):
        if self.script is not None:
            try:
                self.metadata['sampling'] = self.script.exports_sync.stop()
                deadline = time.monotonic() + 1.0
                while self.samples < self.metadata['sampling']['sampled'] and time.monotonic() < deadline:
                    time.sleep(.005)
                if self.samples != self.metadata['sampling']['sampled']:
                    self.errors.append('sample delivery count differs from sampler count')
                if not self.ui_only:
                    self.calibrate()
            except Exception as exc:
                self.errors.append(repr(exc))
            try:
                self.script.unload()
            except Exception as exc:
                self.errors.append(repr(exc))
            self.script = None
        if self.session is not None:
            try:
                self.session.detach()
            except Exception as exc:
                self.errors.append(repr(exc))
            self.session = None
        with self.lock:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
        self.metadata.update(samples=self.samples, errors=self.errors, clock_brackets=self.clocks)
        self.output.with_suffix('.metadata.json').write_text(json.dumps(self.metadata, indent=2), encoding='utf-8')
        return self.metadata
