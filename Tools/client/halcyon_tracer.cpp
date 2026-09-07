// Project Halcyon — 32-bit In-Process Tracing DLL for Vainglory PC (WoW64 x86)
// Targets MSVC 32-bit (__thiscall convention, ECX = this).
// Reverses and exposes CKinActor, CKinActorNav, CKinActorAttributes, and CKinActorGameplayFlags.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <math.h>

#define EXPORT __declspec(dllexport)

// ==============================================================================
// In-Memory Engine Structures (Recovered 2026-09-07)
// ==============================================================================

#pragma pack(push, 1)

struct Vector3 {
    float x;
    float y;
    float z;
};

// VTable 0x127B478
struct CKinActorAttributes {
    void* vtable_primary;           // +0x00 (0x127B478)
    uint8_t pad_04[0x1C];           // +0x04
    float base_max_health;          // +0x20
    uint8_t pad_24[0xB0];           // +0x24
    float max_health_modifier;      // +0xD4
    uint8_t pad_D8[0x164];          // +0xD8
    float AdditionalStatMod;        // +0x23C
    uint8_t pad_240[0xB0];          // +0x240
    float current_health;           // +0x2F0 (Current HP)
    float current_shield;           // +0x2F4 (Current Barrier / Shield)
};

// VTable 0x1282970, Size = 0x7DC
struct CKinActorNav {
    void* vtable;                   // +0x00 (0x1282970)
    uint8_t pad_04[0x04];           // +0x04
    struct CKinActor* owning_actor; // +0x08 (Backpointer to CKinActor)
    uint8_t pad_0C[0x08];           // +0x0C
    uint32_t nav_flags_14;          // +0x14
    uint8_t pathfinder[0x75C];      // +0x18
    Vector3 destination;            // +0x774 (Target coordinate x, y, z)
    Vector3 current_waypoint;       // +0x780 (Current navmesh waypoint x, y, z)
    Vector3 intermediate_vec;       // +0x78C
    Vector3 start_position;         // +0x798
    uint32_t pad_7A4;               // +0x7A4
    struct CKinActor* target_actor; // +0x7A8 (Target entity pointer, 0 if position move)
    uint32_t target_timestamp;      // +0x7AC
    Vector3 facing_direction;       // +0x7B0 (Normalized facing vector: x, y, z)
    uint32_t pad_7BC;               // +0x7BC
    uint8_t path_flags_7D0;         // +0x7D0 (bit 0 = active path)
    uint8_t pad_7D1[3];             // +0x7D1
    uint32_t nav_status;            // +0x7D4 (0x01 = moving to point, 0x02 = moving to target, 0x03 = idle)
    uint8_t override_flags_7D8;     // +0x7D8 (bit 0 = override facing active)
};

// VTable 0x127B448
struct CKinActor {
    void* vtable_primary;           // +0x00 (0x127B448)
    uint8_t pad_04[0x08];           // +0x04
    void* component_list_head;      // +0x0C (Linked list of attached components)
    void* pad_10;                   // +0x10
    void* vtable_referenceable;     // +0x14 (0x127B458)
    uint8_t pad_18[0x08];           // +0x18
    CKinActorAttributes* attributes;// +0x20 (Pointer to attributes component)
    CKinActorNav* navigation;       // +0x24 (Pointer to navigation component)
    void* representation;           // +0x28 (Pointer to CKinActorRep: mesh, anim)
    void* physics_sim;              // +0x2C (Pointer to physics/collision)
    void* scene_node;               // +0x30
    uint8_t pad_34[0x14];           // +0x34
    uint32_t component_slot_mask;   // +0x48
    uint8_t pad_4C[0x04];           // +0x4C
    uint8_t component_slots[0x180]; // +0x50 (32 bytes per slot)
    struct CKinActor* self_ptr;     // +0x130 (Pointer to this)
    uint8_t pad_134[0x34];          // +0x134
    Vector3 position;               // +0x168 (World position: x, y, z)
    uint32_t pad_174;               // +0x174
    uint32_t entity_id;             // +0x178 (Entity ID: e.g. 1500, 1515, etc.)
    uint8_t team_tag;               // +0x17C (Team tag: 0x01 = Team 1, 0x02 = Team 2)
    uint8_t pad_17D[0x5B];          // +0x17D
    float elevation_offset;         // +0x1D8 (Elevation height offset added to position.y)
    uint32_t pad_1DC;               // +0x1DC
    uint32_t entity_flags;          // +0x1E0 (Bitmask: 0x01=LocalPlayer, 0x02=Moving, 0x10=Targetable/Alive, 0x100=Bot/Minion)
    uint16_t state_flags;           // +0x1E4
    uint8_t pad_1E6[0x12];          // +0x1E6
    uint8_t status_byte;            // +0x1F8 (bit 4 = 0x10 invulnerable/godmode)
};

#pragma pack(pop)

// ==============================================================================
// Logging & Diagnostics
// ==============================================================================

static FILE* g_log_file = NULL;

static void Log(const char* fmt, ...) {
    if (!g_log_file) {
        g_log_file = fopen("halcyon_pc_trace.log", "a");
        if (!g_log_file) return;
    }
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log_file, fmt, args);
    va_end(args);
    fflush(g_log_file);
}

extern "C" {

EXPORT void DissectActor(CKinActor* actor) {
    if (!actor) return;
    float yaw_deg = 0.0f;
    float hp = -1.0f;
    float max_hp = -1.0f;

    if (actor->navigation) {
        float x = actor->navigation->facing_direction.x;
        float z = actor->navigation->facing_direction.z;
        yaw_deg = atan2f(z, x) * 57.2957795f;
    }
    if (actor->attributes) {
        hp = actor->attributes->current_health;
        max_hp = actor->attributes->base_max_health;
    }

    Log("[HalcyonTracer] EID=%u Team=%u Pos=(%.2f, %.2f, %.2f) HP=%.1f/%.1f Yaw=%.1f° Flags=0x%08X (Moving=%d, Player=%d)\n",
        actor->entity_id,
        (uint32_t)actor->team_tag,
        actor->position.x, actor->position.y, actor->position.z,
        hp, max_hp,
        yaw_deg,
        actor->entity_flags,
        (actor->entity_flags & 0x02) ? 1 : 0,
        (actor->entity_flags & 0x01) ? 1 : 0
    );
}

EXPORT void DumpAllActors() {
    uintptr_t base = (uintptr_t)GetModuleHandleA(NULL);
    if (!base) return;

    uint32_t* pCount = (uint32_t*)(base + 0x20E7408 - 0x00400000);
    uintptr_t* pTable = (uintptr_t*)(base + 0x20E7404 - 0x00400000);

    if (!pCount || !pTable || !*pTable) {
        Log("[HalcyonTracer] Global entity table not initialized\n");
        return;
    }

    uint32_t count = *pCount;
    uintptr_t table = *pTable;
    Log("[HalcyonTracer] Scanning Entity Table at 0x%p (Count: %u)\n", (void*)table, count);

    for (uint32_t i = 0; i < count; ++i) {
        uintptr_t entry = table + i * 0xB8;
        uint32_t eid = *(uint32_t*)(entry + 4);
        if (eid == 0 || eid == 0xFFFFFFFF) continue;

        // Query actor instance via FindEntityById (0x857970)
        typedef CKinActor* (__cdecl *FindEntityFn)(uint32_t);
        FindEntityFn FindEntity = (FindEntityFn)(base + 0x857970 - 0x00400000);
        CKinActor* actor = FindEntity(eid);
        if (actor) {
            DissectActor(actor);
        }
    }
}

} // extern "C"

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinstDLL);
        Log("\n=== Project Halcyon PC Dissection Tracer Attached (x86 WoW64) ===\n");
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        Log("=== Project Halcyon PC Dissection Tracer Detached ===\n");
        if (g_log_file) {
            fclose(g_log_file);
            g_log_file = NULL;
        }
    }
    return TRUE;
}
