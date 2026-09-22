// Read-only, code-anchored data access. No ARM calls, Interceptor, or heap scan.
const cfg = __CONFIG__;
const base = ptr(cfg.base);
for (const anchor of cfg.anchors) {
    const bytes = new Uint8Array(base.add(anchor.va).readByteArray(anchor.bytes.length));
    if (!anchor.bytes.every((value, i) => bytes[i] === value))
        throw new Error('mapped code anchor mismatch at ' + anchor.va);
}
const clockGettime = new NativeFunction(
    Process.getModuleByName('libc.so').getExportByName('clock_gettime'), 'int', ['int', 'pointer']);
const ts = Memory.alloc(16);
function monotonicMs() {
    if (clockGettime(1, ts) !== 0) throw new Error('clock_gettime failed');
    return ts.readS64().toNumber() * 1000 + ts.add(8).readS64().toNumber() / 1e6;
}
const manager = base.add(0x3114978).readPointer();
const registry = manager.readPointer();
const entityType = base.add(0x2b09220).readU32();
const navType = base.add(0x304f724).readU32();
if (entityType > 4096 || navType > 4096) throw new Error('invalid registered type');
const pool = registry.add(entityType * 0x2e8);
const stride = pool.add(0xa8).readU32();
const storage = pool.add(0x2c8).readPointer();
const order = pool.add(0x2d0).readPointer();
const capacity = pool.add(0x2d8).readU16();
const count = pool.add(0x2da).readU16() & 0x7fff;
const flags = pool.add(0x2e0).readPointer();
if (count > 200 || count > capacity || capacity > 4096 || stride < 0x264 || stride > 65536)
    throw new Error('invalid entity pool bounds');
function retiring(slot) { return (flags.add(slot >> 3).readU8() & (1 << (slot & 7))) !== 0; }
let hero = null, heroSlot = null;
for (let i = capacity - count; i < capacity; i++) {
    const slot = order.add(i * 2).readU16();
    if (slot >= capacity) throw new Error('entity index outside pool');
    if (retiring(slot)) continue;
    const entity = storage.add(stride * slot);
    if (entity.add(0x260).readU32() === cfg.eid) {
        if (hero !== null) throw new Error('duplicate owner EID');
        hero = entity; heroSlot = slot;
    }
}
if (hero === null) throw new Error('owner EID absent');
const entityGeneration = hero.add(0x30).readU32();
let nav = hero.add(0x18).readPointer();
const visited = new Set();
while (!nav.isNull()) {
    if (visited.has(nav.toString()) || visited.size >= 64) throw new Error('component cycle/limit');
    visited.add(nav.toString());
    if (nav.add(8).readPointer().add(0xa4).readU32() === navType) break;
    nav = nav.add(0x20).readPointer();
}
if (nav.isNull() || !nav.add(0x10).readPointer().equals(hero)) throw new Error('navigation owner mismatch');
const identity = {eid: cfg.eid, base: base.toString(), entity: hero.toString(),
    navigation: nav.toString(), entity_type: entityType, navigation_type: navType,
    pool_slot: heroSlot, entity_generation: entityGeneration};
function modelTransform() {
    // c58004 forwards position through the +50 interface. 8a8720 returns
    // the component+28 interface; 8ad524 forwards to its +20 model object.
    // 8a9d6c binds that owner's mesh resource, and d7cce0 writes translation
    // in the 4x4 matrix returned by d7ccd0. 8b2364 binds animation to it.
    const receiver=hero.add(0x50).readPointer();
    if(receiver.isNull() || !receiver.readPointer().equals(base.add(0x26c1c80)) ||
        !receiver.readPointer().add(0x168).readPointer().equals(base.add(0x8ad524)))
        throw new Error('model presentation interface unqualified');
    const component=receiver.sub(0x28), model=receiver.add(0x20).readPointer();
    if(!component.add(0x10).readPointer().equals(hero) || model.isNull() ||
        !model.readPointer().equals(base.add(0x27208a0)) || !model.add(0x10).readPointer().equals(hero) ||
        model.add(8).readPointer().add(0xa4).readU32()!==base.add(0x302ead4).readU32() ||
        !model.readPointer().add(0x30).readPointer().equals(base.add(0xd7ccd0)))
        throw new Error('model object owner/type/getter unqualified');
    const resource=model.add(0x58).readPointer();
    if(resource.isNull() || resource.add(8).readU32()!==1 || resource.add(0x28).readPointer().isNull())
        throw new Error('model mesh resource not loaded');
    const matrix=Array.from({length:16},(_,i)=>model.add(0x70+i*4).readFloat());
    if(!matrix.every(Number.isFinite) || matrix[3]!==0 || matrix[7]!==0 || matrix[11]!==0 || matrix[15]!==1)
        throw new Error('invalid affine model world matrix');
    if(!hero.add(0x50).readPointer().equals(receiver) || !receiver.add(0x20).readPointer().equals(model) ||
        !model.add(0x58).readPointer().equals(resource)) throw new Error('model binding changed during read');
    return {object:model.toString(), component:component.toString(), resource:resource.toString(),
        matrix_column_major:matrix, translation_xyz:matrix.slice(12,15)};
}
function snapshot() {
    const start = monotonicMs();
    if (!base.add(0x3114978).readPointer().equals(manager) || !manager.readPointer().equals(registry) ||
        !pool.add(0x2c8).readPointer().equals(storage) || retiring(heroSlot) ||
        hero.add(0x260).readU32() !== cfg.eid || hero.add(0x30).readU32() !== entityGeneration ||
        !nav.add(0x10).readPointer().equals(hero))
        throw new Error('client entity lifetime changed');
    const pos = [0x250, 0x254, 0x258].map(x => hero.add(x).readFloat());
    const correction = [0x808, 0x80c, 0x810, 0x814].map(x => nav.add(x).readFloat());
    if (![...pos, ...correction].every(Number.isFinite)) throw new Error('nonfinite client state');
    const result = {guest_monotonic_ms: start, position_xyz: pos, correction_velocity_xyz: correction.slice(0, 3),
        correction_remaining_s: correction[3], navigation_flags: nav.add(0x818).readU8(),
        navigation_mode: nav.add(0x18).readPointer().toString()};
    if(cfg.model_transform) result.model=modelTransform();
    result.read_ms=monotonicMs()-start;
    return result;
}
function nativePath() {
    // c60ff4 -> df09b4/df09f8 constructs this array; df0f78 advances it.
    // Read twice to reject concurrent replanning, even at equal count/index.
    const observed=snapshot(), path=nav.add(0x30);
    const count=path.add(0x764).readU32(), index=path.add(0x774).readU32();
    if(count>128 || (count>0 && index>=count)) throw new Error('invalid native path bounds');
    const xyz=(p,o)=>[0,4,8].map(x=>p.add(o+x).readFloat());
    const points=Array.from({length:count},(_,i)=>xyz(path,0x164+i*12));
    const destination=xyz(nav,0x7b0), cursor=xyz(path,0x768);
    if(![...points.flat(),...destination,...cursor].every(Number.isFinite))
        throw new Error('nonfinite native path');
    const second=Array.from({length:count},(_,i)=>xyz(path,0x164+i*12));
    if(path.add(0x764).readU32()!==count || path.add(0x774).readU32()!==index ||
       JSON.stringify(points)!==JSON.stringify(second) ||
       JSON.stringify(destination)!==JSON.stringify(xyz(nav,0x7b0)))
        throw new Error('native path changed during read');
    if(snapshot().navigation_flags!==observed.navigation_flags)
        throw new Error('native path mode changed during read');
    return {identity,observed,count,index,points,cursor,destination,
            mesh_index:path.add(0x778).readU32()};
}
function resources() {
    const start = monotonicMs();
    snapshot();  // Reuse the qualified entity/lifetime checks.
    const stats = hero.add(0x40).readPointer();
    if (stats.isNull()) throw new Error('entity resources absent');
    const field = offset => stats.add(offset).readFloat();
    // 1053 c04408 and 1054 c01624 both consume this same current-resource array.
    const current = {hp: field(0x308), energy: field(0x310), barrier: field(0x318),
        fortified: field(0x31c), gold: field(0x320), xp: field(0x328)};
    const attribute = index => ({base: field(0x38 + index * 4), bonus: field(0xec + index * 4),
        multiplier: field(0x1a0 + index * 4), bonus_multiplier: field(0x254 + index * 4)});
    const maximum = index => {
        const a = attribute(index);
        const value = (a.base + a.bonus * (1 + a.bonus_multiplier)) * (1 + a.multiplier);
        const upper = base.add(0x30a9790 + index * 4).readFloat();
        const lower = base.add(0x30a96d0 + index * 4).readFloat();
        if (![...Object.values(a), value, upper, lower].every(Number.isFinite) || lower > upper)
            throw new Error('invalid native resource attributes');
        return Math.max(lower, Math.min(upper, value));
    };
    const score = {kills: maximum(41), deaths: maximum(42),
        assists: field(0x334), farm: field(0x340)};
    if (!Object.values(score).every(v => Number.isInteger(v) && v >= 0))
        throw new Error('invalid native HUD counters');
    const result = {guest_monotonic_ms: start, eid: cfg.eid, current, score,
        weapon_power: maximum(4), weapon_power_layers: attribute(4),
        movement_speed_layers: attribute(18),
        max_hp: maximum(0), max_energy: maximum(2)};
    if (!hero.add(0x40).readPointer().equals(stats) || !Object.values(current).every(Number.isFinite))
        throw new Error('resource lifetime changed or nonfinite state');
    result.read_ms = monotonicMs() - start;
    return result;
}
function movementModifiers() {
    // c9ee8c consumes attribute18 plus c772c8's typed descendant modifiers.
    // Enumerate only this owned entity's component tree, never heap memory.
    snapshot();
    const wanted=base.add(0x30a9318).readU32(), pending=[hero], visited=new Set(), matches=[];
    while(pending.length){
        const node=pending.pop(),key=node.toString();
        if(visited.has(key)||visited.size>=800)throw Error('movement component cycle/bound');
        visited.add(key);
        if(node.add(8).readPointer().add(0xa4).readU32()===wanted){
            const magnitude=node.add(0x34).readFloat(),flags=node.add(0x50).readU8();
            if(!Number.isFinite(magnitude)||(flags&3)>2)throw Error('invalid movement modifier');
            matches.push({component:key,magnitude,flags,target_handle:node.add(0x38).readPointer().toString(),
                target_generation:node.add(0x40).readU32(),direction:[node.add(0x48).readFloat(),node.add(0x4c).readFloat()]});
        }
        let child=node.add(0x18).readPointer(),siblings=0;
        while(!child.isNull()){
            if(++siblings>800||!child.add(0x10).readPointer().equals(node))throw Error('movement component parent/bound');
            pending.push(child);child=child.add(0x20).readPointer();
        }
    }
    snapshot();
    return {eid:cfg.eid,type_id:wanted,visited:visited.size,components:matches,
            base_layers:resources().movement_speed_layers};
}
function inventory() {
    snapshot();
    // 1085 c03188 -> c5c5c4 -> c72a18. The entity's +68 component
    // holds bounded item slots; c70fc4 and c7175c/c71764 identify both IDs.
    const component = hero.add(0x68).readPointer();
    if (component.isNull() || !component.add(0x10).readPointer().equals(hero))
        throw new Error('inventory owner mismatch');
    const state = component.add(0xdc).readU16();
    const capacity = (state >> 8) & 0x7f, count = state & 0xff;
    if (capacity > 20 || count > capacity) throw new Error('invalid inventory bounds');
    const items = [];
    for (let slot = 0; slot < capacity; slot++) {
        const item = component.add(0x38 + slot * 8).readPointer();
        if (item.isNull()) continue;
        if (!item.add(0x10).readPointer().equals(component)) throw new Error('item owner mismatch');
        items.push({slot, item: item.add(0x48).readU32(), instance: item.add(0x4c).readU32(),
            quantity: item.add(0x50).readU16()});
    }
    if (items.length !== count || component.add(0xdc).readU16() !== state ||
        !hero.add(0x68).readPointer().equals(component)) throw new Error('inventory changed during read');
    snapshot();
    return {eid: cfg.eid, component: component.toString(), capacity, items};
}
function uiState() {
    // e0061c -> root; e02710 -> child/sibling traversal and flags 0x0c;
    // e0d3a4/e08be8/810394 -> bounded UTF-16 text, NOT an image/OCR path.
    const root = base.add(0x3110ce8).readPointer();
    if (root.isNull()) throw new Error('native UI root absent');
    const pending = [root], seen = new Set(), labels = [];
    while (pending.length) {
        const widget = pending.pop();
        if (widget.isNull()) continue;
        const key = widget.toString();
        if (seen.has(key) || seen.size >= 1024) throw new Error('native UI cycle/node limit');
        seen.add(key);
        pending.push(widget.add(0x30).readPointer());
        if ((widget.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(widget.add(0x28).readPointer());
        if (!widget.readPointer().equals(base.add(0x2726530))) continue;
        const count = widget.add(0xd8).readU32();
        const buffer = widget.add(0xe0).readPointer();
        if (count > 4096 || (count && buffer.isNull())) throw new Error('invalid native label');
        if (count) labels.push(buffer.readUtf16String(count));
    }
    if (!base.add(0x3110ce8).readPointer().equals(root)) throw new Error('native UI root changed');
    return {root: root.toString(), nodes: seen.size, labels,
        limit: 'Active native text only; untranslated/unknown panels are not classified.'};
}
function defaultItemControl(instance) {
    snapshot();
    if (!Number.isInteger(instance) || instance <= 0) throw new Error('invalid item instance');
    const root = base.add(0x3110ce8).readPointer();
    if (root.isNull()) throw new Error('native UI root absent');
    const pending = [root], seen = new Set(), found = [];
    while (pending.length) {
        const p = pending.pop();
        if (p.isNull()) continue;
        if (seen.has(p.toString()) || seen.size >= 1024) throw new Error('native UI cycle/node limit');
        seen.add(p.toString());
        pending.push(p.add(0x30).readPointer());
        if ((p.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(p.add(0x28).readPointer());
        // 9300f8 binds the native inventory component and item instance here.
        if (!p.readPointer().equals(base.add(0x26c9198)) || p.add(0x770).readU32() !== instance) continue;
        const component = p.add(0x758).readPointer();
        if (component.isNull() || !component.add(0x10).readPointer().equals(hero))
            throw new Error('default item owner mismatch');
        const touch = p.add(0x698), v = touch.readPointer();
        if ((touch.add(0x84).readU32() & 28) !== 28 ||
            !v.add(0x48).readPointer().equals(base.add(0xe13e54)) ||
            !v.add(0x68).readPointer().equals(base.add(0xe02010)) ||
            !v.add(0x70).readPointer().equals(base.add(0xe020b4)))
            throw new Error('unqualified item touch layout');
        const count = touch.add(8).readU32(), events = touch.add(0x10).readPointer();
        if (count > 16 || events.isNull()) throw new Error('invalid item event binding');
        let bindings = 0;
        for (let i = 0; i < count; i++) {
            const event = events.add(i * 0x30);
            if (event.readPointer().equals(base.add(0x9305c8)) && event.add(8).readPointer().equals(p)) bindings++;
        }
        if (bindings !== 2) throw new Error('default item callback not verified');
        const anchor = [0x50, 0x54].map(x => touch.add(x).readFloat());
        const origin = [0x68, 0x6c].map(x => touch.add(x).readFloat());
        const scale = [0x70, 0x74].map(x => touch.add(x).readFloat());
        const size = [0x90, 0x94].map(x => touch.add(x).readFloat());
        if (![...anchor, ...origin, ...scale, ...size].every(Number.isFinite) ||
            !scale.every(x => x > 0) || !size.every(x => x > 0)) throw new Error('invalid item bounds');
        const clip = [0, 2, 4, 6].map(x => touch.add(0x7c + x).readS16());
        const center = origin.map((x, i) => Math.round(x + (0.5 - anchor[i]) * scale[i] * size[i]));
        if (!(center[0] > Math.max(0, clip[0]) && center[0] < Math.min(960, clip[2]) &&
              center[1] > Math.max(0, clip[1]) && center[1] < Math.min(540, clip[3])))
            throw new Error('item touch center outside pinned viewport/clip');
        found.push({eid: cfg.eid, instance, widget: p.toString(), touch: touch.toString(),
            component: component.toString(), center, anchor, origin, scale, size, clip});
    }
    if (found.length !== 1 || !base.add(0x3110ce8).readPointer().equals(root))
        throw new Error('default item UI absent, ambiguous or changed');
    snapshot();
    return found[0];
}
function actorStates(eids) {
    const started=monotonicMs();snapshot();
    if(!Array.isArray(eids) || eids.length>64 ||
        !eids.every(e=>Number.isInteger(e)&&e>=0&&e<=0xffffffff) || new Set(eids).size!==eids.length)
        throw new Error('invalid bounded actor request');
    const requested=new Set(eids), found=[];
    const currentCount=pool.add(0x2da).readU16()&0x7fff;
    if(currentCount>200 || currentCount>capacity || pool.add(0x2d8).readU16()!==capacity ||
        !pool.add(0x2d0).readPointer().equals(order) || !pool.add(0x2e0).readPointer().equals(flags))
        throw new Error('actor registry bounds/lifetime changed');
    for(let i=capacity-currentCount;i<capacity;i++) {
        const slot=order.add(i*2).readU16();
        if(slot>=capacity)throw new Error('actor slot outside pool');
        if(retiring(slot))continue;
        const entity=storage.add(slot*stride), eid=entity.add(0x260).readU32();
        if(!requested.has(eid))continue;
        const generation=entity.add(0x30).readU32(), definition=entity.add(0x38).readPointer(),stats=entity.add(0x40).readPointer();
        if(definition.isNull() || stats.isNull())throw new Error('actor definition/resources absent');
        const position=[0x250,0x254,0x258].map(o=>entity.add(o).readFloat());
        const center=position.slice();center[1]+=entity.add(0x2ec).readFloat();
        const scale=definition.add(0x64).readFloat(), extra=entity.add(0x2e8).readFloat();
        let radius=definition.add(0x70).readFloat();if(radius<=0)radius=definition.add(0x68).readFloat();
        radius=radius*(scale+extra)/scale;
        const height=definition.add(0x6c).readFloat(),hp=stats.add(0x308).readFloat();
        const barrier=stats.add(0x318).readFloat(),fortified=stats.add(0x31c).readFloat();
        const hpLayers=[0x38,0xec,0x1a0,0x254].map(o=>stats.add(o).readFloat());
        const maxHp=Math.max(base.add(0x30a96d0).readFloat(),Math.min(base.add(0x30a9790).readFloat(),
            (hpLayers[0]+hpLayers[1]*(1+hpLayers[3]))*(1+hpLayers[2])));
        if(![...position,...center,...hpLayers,scale,extra,radius,height,hp,barrier,fortified,maxHp].every(Number.isFinite) || scale<=0 ||
            radius<0 || radius>100 || height<0 || height>100 || hp<0 || hp>1e9)
            throw new Error('invalid native actor selection state');
        if(retiring(slot) || entity.add(0x260).readU32()!==eid || entity.add(0x30).readU32()!==generation ||
            !entity.add(0x38).readPointer().equals(definition) || !entity.add(0x40).readPointer().equals(stats))
            throw new Error('actor changed during read');
        found.push({eid,generation,position_xyz:position,hp,barrier,fortified,max_hp:maxHp,hp_layers:hpLayers,selection_center_xyz:center,
            selection_radius:radius,selection_height:height});
    }
    if(new Set(found.map(a=>a.eid)).size!==found.length)throw new Error('duplicate requested actor EID');
    return {guest_monotonic_ms:started,read_ms:monotonicMs()-started,actors:found,
        missing:eids.filter(e=>!found.some(a=>a.eid===e)),source:'typed entity registry -> c5b4e0 native pick capsule'};
}
function selectedTarget() {
    snapshot();
    // 9153f0 binds hero+2b0 to selected actor+28 and copies actor+30
    // generation to hero+2b8. Identical selection bypasses the1060 sender.
    const handle=hero.add(0x2b0).readPointer(),generation=hero.add(0x2b8).readU32();
    if(handle.isNull())return {eid:cfg.eid,target_eid:null};
    const target=handle.sub(0x28);
    if(target.compare(storage)<0 || target.compare(storage.add(capacity*stride))>=0)
        throw new Error('selected actor outside typed registry');
    const delta=target.sub(storage).toInt32();
    if(delta<0 || delta%stride!==0 || delta/stride>=capacity)throw new Error('selected actor outside typed registry');
    const slot=delta/stride;
    if(retiring(slot) || target.add(0x30).readU32()!==generation)
        return {eid:cfg.eid,target_eid:null,expired_generation:true};
    const eid=target.add(0x260).readU32();
    if(!hero.add(0x2b0).readPointer().equals(handle) || hero.add(0x2b8).readU32()!==generation)
        throw new Error('native selection changed during read');
    return {eid:cfg.eid,target_eid:eid,generation,source:'9153f0 owner native selection weak handle'};
}
function cameraView() {
    const started=monotonicMs(), observed=snapshot();
    const controller=base.add(0x3030c48).readPointer();
    if(controller.isNull() || !controller.add(0x340).readPointer().equals(hero))
        throw new Error('camera input owner not qualified');
    // 81ef04/81ef94 -> 8bbfb0 -> 8bd5c8 -> 8b87f0/8b891c.
    // Never call the lazy native matrix updater from the translated realm.
    const cameraManager=base.add(0x302ede8).readPointer();
    if(cameraManager.isNull())throw new Error('active camera manager absent');
    const camera=cameraManager.add(0x2b0).readPointer();
    if(camera.isNull() || !camera.readPointer().equals(base.add(0x26c2288)))
        throw new Error('unqualified active camera');
    const root=base.add(0x3110ce8).readPointer();
    if(root.isNull() || (camera.add(0x7c).readU8()&2))throw new Error('camera matrices dirty/absent');
    const read=(offset,n)=>Array.from({length:n},(_,i)=>camera.add(offset+4*i).readFloat());
    const view=read(0x18c,16), projection=read(0x20c,16);
    const dimensions=[root.add(0x1b0).readFloat(),root.add(0x1b4).readFloat()];
    if(![...view,...projection,...dimensions].every(Number.isFinite) ||
        !dimensions.every(v=>Number.isInteger(v)&&v>0&&v<=8192) ||
        view[3]!==0 || view[7]!==0 || view[11]!==0 || view[15]!==1 ||
        projection[11]!==-1 || projection[15]!==0)
        throw new Error('invalid native perspective/viewport');
    if(!read(0x18c,16).every((v,i)=>v===view[i]) || !read(0x20c,16).every((v,i)=>v===projection[i]) ||
        (camera.add(0x7c).readU8()&2) || !cameraManager.add(0x2b0).readPointer().equals(camera) ||
        !base.add(0x302ede8).readPointer().equals(cameraManager) ||
        !base.add(0x3110ce8).readPointer().equals(root))throw new Error('camera changed during read');
    return {eid:cfg.eid,guest_monotonic_ms:started,read_ms:monotonicMs()-started,
        camera:camera.toString(),dimensions,view,projection,owner_position_xyz:observed.position_xyz,
        source:'81ef94 -> 8b891c active native world-to-screen matrices'};
}
function cameraControl() {
    snapshot();
    const preferences = base.add(0x3030890).readPointer();
    const controller = base.add(0x3030c48).readPointer();
    if (preferences.isNull() || controller.isNull() ||
        !controller.add(0x340).readPointer().equals(hero))
        throw new Error('camera input owner not qualified');
    const locked = preferences.add(0x28).readU32();
    if (locked > 1) throw new Error('invalid camera-lock preference');
    const root = base.add(0x3110ce8).readPointer();
    const pending = [root], seen = new Set(), matches = [];
    while (pending.length) {
        const p = pending.pop();
        if (p.isNull()) continue;
        if (seen.has(p.toString()) || seen.size >= 1024) throw new Error('camera UI cycle/node limit');
        seen.add(p.toString()); pending.push(p.add(0x30).readPointer());
        if ((p.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(p.add(0x28).readPointer());
        if (!p.readPointer().equals(base.add(0x26cd518)) || (p.add(0x84).readU32() & 16) === 0) continue;
        const count = p.add(8).readU32(), events = p.add(0x10).readPointer();
        if (count > 16 || (count && events.isNull())) throw new Error('invalid camera UI events');
        for (let i = 0; i < count; i++) {
            const event = events.add(i * 0x30);
            if (event.add(0x28).readU32() !== 10712282 ||
                !event.readPointer().equals(base.add(0x93b354))) continue;
            const v = p.readPointer();
            // The native texture button is center-anchored, so its cached
            // origin is the center regardless of the texture's dynamic size.
            if (!v.add(0x68).readPointer().equals(base.add(0xe02010)) ||
                p.add(0x50).readFloat() !== .5 || p.add(0x54).readFloat() !== .5)
                throw new Error('unqualified camera touch layout');
            const center = [p.add(0x68).readFloat(), p.add(0x6c).readFloat()];
            const clip = [0, 2, 4, 6].map(o => p.add(0x7c + o).readS16());
            if (!center.every(Number.isFinite) || center[0] <= Math.max(0, clip[0]) ||
                center[0] >= Math.min(960, clip[2]) || center[1] <= Math.max(0, clip[1]) ||
                center[1] >= Math.min(540, clip[3])) throw new Error('camera control outside clip');
            matches.push({eid: cfg.eid, locked: Boolean(locked), widget: p.toString(),
                center: center.map(Math.round), clip});
        }
    }
    if (matches.length !== 1 || !base.add(0x3110ce8).readPointer().equals(root) ||
        preferences.add(0x28).readU32() !== locked)
        throw new Error('camera control absent, ambiguous or changed');
    return matches[0];
}
function utilityControl(item) {
    snapshot();
    const controller = base.add(0x3030c48).readPointer();
    if (controller.isNull() || !controller.add(0x340).readPointer().equals(hero))
        throw new Error('Recall input owner not qualified');
    const root = base.add(0x3110ce8).readPointer();
    const pending = [root], seen = new Set(), found = [];
    while (pending.length) {
        const p = pending.pop();
        if (p.isNull()) continue;
        if (seen.has(p.toString()) || seen.size >= 1024) throw new Error('Recall UI cycle/node limit');
        seen.add(p.toString()); pending.push(p.add(0x30).readPointer());
        if ((p.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(p.add(0x28).readPointer());
        if ((p.add(0x84).readU32() & 16) === 0 || !p.readPointer().equals(base.add(0x26c8b40))) continue;
        const count = p.add(8).readU32(), events = p.add(0x10).readPointer();
        if (count > 16 || (count && events.isNull())) throw new Error('invalid Recall events');
        let matches = 0;
        for (let i = 0; i < count; i++) {
            const e = events.add(i * 0x30);
            if ([12439691, 14900802].includes(e.add(0x28).readU32()) &&
                e.readPointer().equals(base.add(0x96eb98)) && e.add(0x20).readU32() === item &&
                e.add(8).readPointer().add(item === 0 ? 0x248 : 0x448).equals(p)) matches++;
        }
        if (!matches) continue;
        if (matches !== 2 || !p.readPointer().add(0x68).readPointer().equals(base.add(0xe02010)) ||
            p.add(0x50).readFloat() !== .5 || p.add(0x54).readFloat() !== .5)
            throw new Error('Recall binding/layout unqualified');
        const center = [p.add(0x68).readFloat(), p.add(0x6c).readFloat()];
        const clip = [0, 2, 4, 6].map(o => p.add(0x7c + o).readS16());
        if (!center.every(Number.isFinite) || center[0] <= Math.max(0, clip[0]) ||
            center[0] >= Math.min(960, clip[2]) || center[1] <= Math.max(0, clip[1]) ||
            center[1] >= Math.min(540, clip[3])) throw new Error('Recall center outside viewport/clip');
        found.push({eid: cfg.eid, item, widget: p.toString(), center: center.map(Math.round), clip});
    }
    if (found.length !== 1 || !base.add(0x3110ce8).readPointer().equals(root))
        throw new Error('Recall control absent, ambiguous or changed');
    return found[0];
}
function recallControl() { return utilityControl(0); }
function shopControl() { return utilityControl(2); }
function shopItemControl(item) {
    snapshot();
    if (!Number.isInteger(item) || item <= 0) throw new Error('invalid shop item');
    const root = base.add(0x3110ce8).readPointer(), pending = [root], seen = new Set(), found = [];
    while (pending.length) {
        const p = pending.pop();
        if (p.isNull()) continue;
        if (seen.has(p.toString()) || seen.size >= 1024) throw new Error('shop UI cycle/node limit');
        seen.add(p.toString()); pending.push(p.add(0x30).readPointer());
        if ((p.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(p.add(0x28).readPointer());
        if (!p.readPointer().equals(base.add(0x26cc3b8)) || p.add(0xc8).readU32() !== item ||
            (p.add(0x84).readU32() & 16) === 0) continue;
        const count = p.add(8).readU32(), events = p.add(0x10).readPointer();
        if (count > 16 || events.isNull()) throw new Error('invalid shop row events');
        const owners = [];
        for (let i = 0; i < count; i++) {
            const e = events.add(i * 0x30);
            if ([12439691,14900802].includes(e.add(0x28).readU32()) &&
                e.readPointer().equals(base.add(0x965914)) && e.add(0x20).readPointer().equals(p))
                owners.push(e.add(8).readPointer());
        }
        if (owners.length !== 2 || !owners[0].equals(owners[1]) || owners[0].isNull() ||
            !owners[0].add(0xd0).readPointer().equals(hero)) throw new Error('shop item owner/binding mismatch');
        const v = p.readPointer();
        if (!v.add(0x48).readPointer().equals(base.add(0xe13e54)) ||
            !v.add(0x68).readPointer().equals(base.add(0xe02010))) throw new Error('shop row layout unqualified');
        const anchor = [0x50,0x54].map(o=>p.add(o).readFloat());
        const origin = [0x68,0x6c].map(o=>p.add(o).readFloat());
        const scale = [0x70,0x74].map(o=>p.add(o).readFloat());
        const size = [0x90,0x94].map(o=>p.add(o).readFloat());
        if (![...anchor,...origin,...scale,...size].every(Number.isFinite) ||
            ![...scale,...size].every(x=>x>0)) throw new Error('invalid shop row rectangle');
        const center=origin.map((x,i)=>Math.round(x+(.5-anchor[i])*scale[i]*size[i]));
        const clip=[0,2,4,6].map(o=>p.add(0x7c+o).readS16());
        if (center[0]<=Math.max(0,clip[0]) || center[0]>=Math.min(960,clip[2]) ||
            center[1]<=Math.max(0,clip[1]) || center[1]>=Math.min(540,clip[3])) continue;
        found.push({eid:cfg.eid,item,center,clip,widget:p.toString(),
            selected:owners[0].add(0x24d90).readPointer().equals(p)});
    }
    if(found.length!==1 || !base.add(0x3110ce8).readPointer().equals(root))
        throw new Error('shop item absent, offscreen, ambiguous or changed');
    return found[0];
}
function abilityControl(slot, upgrade) {
    snapshot();
    if (![0, 1, 2].includes(slot) || typeof upgrade !== 'boolean')
        throw new Error('invalid ability control request');
    const root = base.add(0x3110ce8).readPointer();
    if (root.isNull()) throw new Error('native UI root absent');
    const pending = [root], seen = new Set(), found = [];
    while (pending.length) {
        const p = pending.pop();
        if (p.isNull()) continue;
        if (seen.has(p.toString()) || seen.size >= 1024) throw new Error('ability UI cycle/node limit');
        seen.add(p.toString()); pending.push(p.add(0x30).readPointer());
        if ((p.add(0x84).readU32() & 12) !== 12) continue;
        pending.push(p.add(0x28).readPointer());
        if ((p.add(0x84).readU32() & 16) === 0) continue;
        let control = p, owner, lifetime, actualSlot, action;
        if (!upgrade) {
            if (!p.readPointer().equals(base.add(0x26c88b0))) continue;
            owner = p.add(0x1a8).readPointer(); lifetime = p.add(0x1b0).readU32();
            actualSlot = p.add(0x1cec).readU32(); action = p.add(0x1ce8).readU32();
        } else {
            const count = p.add(8).readU32(), events = p.add(0x10).readPointer();
            if (count > 16 || (count && events.isNull())) throw new Error('invalid ability UI events');
            const bindings = [];
            for (let i = 0; i < count; i++) {
                const event = events.add(i * 0x30);
                if ([12439691, 14900802].includes(event.add(0x28).readU32()) &&
                    event.readPointer().equals(base.add(0x927d68))) bindings.push(event.add(8).readPointer());
            }
            if (!bindings.length) continue;
            if (bindings.length !== 2 || !bindings[0].equals(bindings[1]) || bindings[0].isNull())
                throw new Error('upgrade callbacks inconsistent');
            control = bindings[0];
            owner = control.add(0xbd0).readPointer(); lifetime = control.add(0xbd8).readU32();
            actualSlot = control.add(0xbe2).readU8(); action = control.add(0xbe0).readU16();
        }
        if (actualSlot !== slot) continue;
        if (!owner.equals(hero.add(0x28)) || lifetime !== hero.add(0x30).readU32())
            throw new Error('ability owner/lifetime mismatch');
        const v = p.readPointer();
        if (!v.add(0x48).readPointer().equals(base.add(0xe13e54)) ||
            !v.add(0x68).readPointer().equals(base.add(0xe02010)) ||
            !v.add(0x70).readPointer().equals(base.add(0xe020b4)))
            throw new Error('unqualified ability rectangle');
        const anchor = [0x50, 0x54].map(o => p.add(o).readFloat());
        const origin = [0x68, 0x6c].map(o => p.add(o).readFloat());
        const scale = [0x70, 0x74].map(o => p.add(o).readFloat());
        const size = [0x90, 0x94].map(o => p.add(o).readFloat());
        if (![...anchor, ...origin, ...scale, ...size].every(Number.isFinite) ||
            ![...scale, ...size].every(x => x > 0)) throw new Error('invalid ability rectangle');
        const clip = [0, 2, 4, 6].map(o => p.add(0x7c + o).readS16());
        const center = origin.map((x, i) => Math.round(x + (.5 - anchor[i]) * scale[i] * size[i]));
        if (center[0] <= Math.max(0, clip[0]) || center[0] >= Math.min(960, clip[2]) ||
            center[1] <= Math.max(0, clip[1]) || center[1] >= Math.min(540, clip[3]))
            throw new Error('ability control outside viewport/clip');
        found.push({eid: cfg.eid, slot, action, upgrade, lifetime, center, clip,
                    widget: p.toString(), control: control.toString()});
    }
    if (found.length !== 1 || !base.add(0x3110ce8).readPointer().equals(root))
        throw new Error('ability control absent, ambiguous or changed');
    snapshot();
    return found[0];
}
function shopBuyControl(item) {
    snapshot();
    if (!Number.isInteger(item) || item <= 0) throw new Error('invalid purchase item');
    // 95c4a8 is the ordinary buy-button event; 95c7b0 binds the detail owner.
    // 95a9f4 selects BUY mode 0 and reads the catalog selection at +29c0.
    const root=base.add(0x3110ce8).readPointer(), pending=[root], seen=new Set(), found=[];
    while(pending.length) {
        const p=pending.pop(); if(p.isNull()) continue;
        if(seen.has(p.toString()) || seen.size>=1024) throw new Error('purchase UI cycle/node limit');
        seen.add(p.toString()); pending.push(p.add(0x30).readPointer());
        if((p.add(0x84).readU32()&12)!==12) continue;
        pending.push(p.add(0x28).readPointer());
        if(!p.readPointer().equals(base.add(0x26d4ec0)) || (p.add(0x84).readU32()&16)===0) continue;
        const count=p.add(8).readU32(), events=p.add(0x10).readPointer();
        if(count>16) throw new Error('purchase event count invalid');
        for(let i=0;i<count;i++) {
            const e=events.add(i*0x30);
            if(e.add(0x28).readU32()!==10712282 || !e.readPointer().equals(base.add(0x95c4a8))) continue;
            const panel=e.add(8).readPointer(), shop=panel.sub(0x2f260);
            if(!panel.add(0x2f8).equals(p) || !panel.add(0xc8).readPointer().equals(hero.add(0x28)) ||
                panel.add(0xd0).readU32()!==hero.add(0x30).readU32() || panel.add(0x2a30).readU32()!==0 ||
                !shop.add(0x29c0+0xd0).readPointer().equals(hero))
                throw new Error('purchase owner/lifetime/mode mismatch');
            const row=shop.add(0x29c0+0x24d90).readPointer();
            if(row.isNull() || !row.readPointer().equals(base.add(0x26cc3b8)) || row.add(0xc8).readU32()!==item)
                throw new Error('purchase selected item mismatch');
            const v=p.readPointer();
            if(!v.add(0x48).readPointer().equals(base.add(0xe13e54)) ||
                !v.add(0x68).readPointer().equals(base.add(0xe02010))) throw new Error('purchase layout unqualified');
            const anchor=[0x50,0x54].map(o=>p.add(o).readFloat()), origin=[0x68,0x6c].map(o=>p.add(o).readFloat());
            const scale=[0x70,0x74].map(o=>p.add(o).readFloat()), size=[0x90,0x94].map(o=>p.add(o).readFloat());
            if(![...anchor,...origin,...scale,...size].every(Number.isFinite) || ![...scale,...size].every(x=>x>0))
                throw new Error('invalid purchase bounds');
            const center=origin.map((x,i)=>Math.round(x+(.5-anchor[i])*scale[i]*size[i]));
            const clip=[0,2,4,6].map(o=>p.add(0x7c+o).readS16());
            if(center[0]<=Math.max(0,clip[0]) || center[0]>=Math.min(960,clip[2]) ||
                center[1]<=Math.max(0,clip[1]) || center[1]>=Math.min(540,clip[3]))
                throw new Error('purchase center outside viewport/clip');
            found.push({eid:cfg.eid,item,center,widget:p.toString(),panel:panel.toString()});
        }
    }
    if(found.length!==1 || !base.add(0x3110ce8).readPointer().equals(root))
        throw new Error('purchase control absent, ambiguous or changed');
    snapshot(); return found[0];
}
let timer = null, pending = [], sampled = 0;
function flush() { if (pending.length) { send({samples: pending}); pending = []; } }
rpc.exports = {
    qualify() { return {identity, snapshot: snapshot()}; },
    snapshot,
    resources,
    movementModifiers,
    defaultItemControl,
    cameraControl,
    cameraView,
    actorStates,
    selectedTarget,
    nativePath,
    abilityControl,
    recallControl,
    shopControl,
    shopItemControl,
    inventory,
    shopBuyControl,
    uiState,
    start() {
        if (timer !== null) throw new Error('already sampling');
        timer = setInterval(() => {
            try { pending.push(snapshot()); sampled++; if (pending.length >= 50) flush(); }
            catch (error) { clearInterval(timer); timer = null; flush(); send({error: String(error)}); }
        }, cfg.period_ms);
    },
    stop() { if (timer !== null) clearInterval(timer); timer = null; flush(); return {sampled}; }
};
