# Local client scenario preparation

`server/sandbox_qa.py` provides a deliberately bounded, opt-in file mailbox for
preparing client acceptance scenarios in the operator's own local match. It
has no network listener, scripting expression, arbitrary property setter or
command execution facility. When `HALCYON_QA_DIR` is absent, startup returns
`None` and no mailbox, state file or fixture work is created.

**Prepared state is diagnostic setup, not acceptance evidence.** After setup,
the operator must drive the actual client controls and observe the requested
gameplay and native wire exchange. For example, setting gold and teleporting
to a shop does not prove a purchase; clicking Buy and observing the accepted
1081 plus inventory change does. Forced damage to a turret does not prove
normal turret combat or natural match progression.

## Enable and integrate

Choose an explicit absolute directory outside this repository. The server
and CLI must use the same value; there is no fallback directory or CLI path
override. Symlink/junction directory paths are rejected.

```powershell
$env:HALCYON_QA_DIR = Join-Path $env:TEMP 'halcyon_sandbox_qa'
# Start the local stack normally with this environment.
python Tools/sandbox_qa.py snapshot
```

The owning match session integrates this module at construction and inside
its existing simulation lock, before advancing the next fixed tick:

```python
self.qa = SandboxQA.from_environment()

# Beginning of advance_simulation, on its existing world thread:
if self.qa is not None:
    self.qa.pump(self)
```

`pump` records the current `sim_tick` and `sim_time`: those are the exact
state boundary at which a fixture was applied. It does not advance the clock,
re-enter the simulation, create a worker thread or change the 50 ms tick.
Mutating commands require an active WORLD phase before match completion.
Snapshots remain available for a finished world if the owning loop pumps it.

## Fixed commands

Each request is one JSON object. `command` is required; extra fields and
duplicate JSON keys are rejected. Entity IDs are positive integer IDs, not
player UUIDs or compact actor slots. Numbers must be finite; booleans are not
accepted as numbers.

| Command | Required fields beyond `command` | Optional fields and behavior |
|---|---|---|
| `snapshot` | None | Return current state without changing the world |
| `teleport` | `eid`, `x`, `y` | Living hero only; coordinates within −1000..1000 are projected to the actual navigation mesh; cancels targeting, movement, recall and uncommitted attack state |
| `resources` | `eid` | At least one of `hp`, `energy`, `gold`; living hero only; HP/energy clamp to current actor caps; HP must be at least 1; gold must be 0..100000 |
| `damage` | `source`, `target`, `amount`, `kind` | Living existing actors; amount 0.001..100000; kind `weapon`, `crystal` or `true`; actual mitigation, faction, barrier, death, bounty and objective rules remain active |
| `status` | `eid`, `type`, `duration` | Living hero; type `STUN`, `SILENCE`, `KNOCKBACK` or `SLOW`; duration 0.001..10 seconds |
| `learn` | `eid`, `slot` | Living hero, slot 0/1/2; prepare and learn exactly the next legal rank through the normal ability validator and economy |

For SLOW only, `magnitude` defaults to 0.5 and must be within 0..0.95. For
KNOCKBACK only, `dx`/`dy` default to 1/0 and are normalized as a nonzero
direction; each component is bounded to −1000..1000. `speed` defaults to 6
and must be within 0.001..20 units per second. These are fixture coefficients,
not claims about a native hero's status strength or duration. Status application
uses `StatusManager`, including current CC immunity and interruption tracking.
Accepted STUN and SILENCE fixtures also use the verified built-in native buff
kinds 22 and 32, shared with ability effects. The normal simulation tick drains
their 1086 presentation, using the requested duration and the target hero as
source. CC immunity rejects both mechanics and presentation without allocating
a buff identity. SLOW and KNOCKBACK retain their fixture mechanics with no
unverified native kind. The KindredBuffs registry and replay anchors for these
two shared kinds are covered by `server/test/test_ability_cc_presentation.py`;
fixture duration remains an explicit diagnostic input.

Resource setup publishes only the actual 1053 changes using HP channel 0,
energy channel 2 and gold channel 6. It does not resurrect a dead hero or
bypass the death lifecycle; use real damage to prepare death and observe the
normal respawn. A requested HP/energy value above the actor cap is reported
back as the clamped actual value.

Damage uses `SnapshotStream._deal_damage` and its native result frames. A hit
can be rejected or reduced by normal game rules; the acknowledgement includes
the damage actually emitted for the original victim. An objective capture may
replace that actor, so the result also names `current_eid`.

Learn asks a copy of the actual kit's rank validator for the earliest level
where the next rank is legal **and** an ability point is available after native
level grants. It grants only the real XP needed to reach that level through
the existing economy reward path, then calls `EconomyManager.upgrade_ability`.
It never invents an additional point. At level 12 with no unspent point, a
request is rejected without mutation even if that ability has room for another
rank. An existing unspent point can still be used at the cap.
The 1078 acknowledgement goes only to the owning connection, because its
payload has no hero ID; 1082 is broadcast with the actual hero ID and native
action ordinal, followed by the measured ready timer when its tag is known.
The result records XP grants; `extra_points_granted` is retained as zero for
compatibility with existing receipt readers. This explicit preparation
does not establish natural leveling or client skill allocation acceptance.

The 2026-09-08 correction closes a reproduced Catherine A→B→C preparation
failure. A consumed the level-one point; the former B preparation added a
private server point without a native grant, leaving the client unable to
learn B despite the correct action-2 acknowledgement. From zero XP the fixed
sequence uses no XP for A, 68 XP to reach level 2 for B, then 432 XP to reach
level 6 for C. It ends with three unspent points on both server and receiver.
The old fallback also allowed 13 total ranks at level 12; that request now
fails honestly.

## CLI examples

```powershell
python Tools/sandbox_qa.py teleport --eid 1500 --x -88.5 --y 2
python Tools/sandbox_qa.py resources --eid 1500 --hp 300 --energy 200 --gold 10000
python Tools/sandbox_qa.py learn --eid 1500 --slot 2
python Tools/sandbox_qa.py status --eid 1500 --type SILENCE --duration 2
python Tools/sandbox_qa.py status --eid 1500 --type KNOCKBACK --duration 0.5 --dx 1 --dy 0 --speed 6
python Tools/sandbox_qa.py damage --source 1517 --target 1500 --amount 50 --kind true
python Tools/sandbox_qa.py snapshot
```

The CLI publishes one complete request with a same-directory atomic replace,
then waits up to five seconds for its acknowledgement. `--timeout` before the
command changes this bound to 0..10 seconds. A timeout reports the request ID
and result path, leaves the original request pending and does not retry it.
Inspect that acknowledgement before submitting another mutating operation.
Exit codes are 0 for success, 1 for a server rejection and 2 for pending or
invalid CLI input. A successful fixture acknowledgement does not imply a
successful subsequent user action.

## Files, ordering and reproduction

Requests are `command-<identifier>.json` directly inside the explicit QA
directory. Identifiers contain 1..64 ASCII letters, digits, underscores or
hyphens. Each command file is limited to 4096 bytes. The pump executes at most
eight commands, in filename order, at one state boundary. Partial `.tmp` files
are ignored. Symlinks, reparse points, non-regular files, changed file identities,
oversized records, unknown fields and nonfinite values are rejected.

Before mutation, an exclusive file under `consumed/` reserves the request ID.
The original incoming request is removed after consumption; `ack-<id>.json`
is published atomically. Existing consumed IDs cannot run again, including
after a server restart. If the process stops after reserving a command but
before its acknowledgement, the command is not automatically replayed: inspect
the journal and current state before deliberately submitting a fresh request.
This provides at-most-once execution, not a transaction across process failure.

`journal.jsonl` records each schema-accepted command and its actual tick/time
before execution, then its completed acknowledgement or rejection. Completed
records with `ok: true` identify applied commands. Retain these records along
with the source revision and local wire trace when reproducing a prepared
scenario. The live simulation contains no wall-clock timing or randomness
introduced by the fixture commands; their recorded order and tick boundaries
are part of the diagnostic input.

`state.json` is a read-only snapshot of the current world, replaced at most
every ten simulation ticks when idle and immediately after command batches.
It contains phase/tick/time, hero positions, life state, HP/EP caps, recall and
respawn times, ranks, inventory instances, remaining ability/item/default-item
cooldowns and active statuses. It includes up to 64 nearby creatures within
40 units of any hero and the first 32 structures in entity-ID order. Snapshot
reads do not create economy accounts, allocate identities, drain frames or
modify cooldowns. File I/O is diagnostic overhead in an explicitly enabled
session; performance acceptance must run with QA disabled.

On Windows, a reader that omits delete sharing can prevent `os.replace` from
replacing an open destination. QA publication errors are now isolated from
the match loop. A failed snapshot keeps the last good file and retries on the
next simulation tick, publishing the latest state. Repeated failures for the
same publication are logged once until a successful retry; they do not block
or stop simulation.

An applied command's failed acknowledgement is retained in memory and retried
on later ticks. At most eight acknowledgements wait; a full backlog pauses new
QA commands while gameplay continues. Durable consumed markers remain the
authority for at-most-once execution, including duplicate requests and process
restart. Failure to record the acceptance journal rejects the claimed command
before execution. Failure to append its completion record is logged, while
its acknowledgement and consumed marker preserve the outcome. Journal appends
are not retried after an uncertain partial write; inspect the receipt and
journal tail if publication failed. A lost acknowledgement after process exit
never authorizes repeating the effect under the same request identity.

These changes affect the opt-in QA path only; the worker used for performance
acceptance has QA disabled. They still change the complete source-manifest
hash. The preceding paired benchmark remains evidence for its recorded source
pin, rather than a claim that the modified manifest was benchmarked.

## Checks

`python -B -m unittest server.test.test_sandbox_qa` passes 26 tests against the
production SnapshotStream session. Coverage includes native resource/damage
frames, normal rank/XP/point handling, owner-only 1078, mesh projection, actual
status displacement, immutable snapshots, bounded batches, atomic CLI submission
and result retrieval, real symlink rejection, invalid JSON/schema cases, and
duplicate prevention after restart. New cases cover the two-receiver Catherine
rank sequence, honest point exhaustion at the level cap, snapshot and receipt
sharing failures, bounded receipt retries, and both journal-failure phases.
Status cases also exercise the production tick's native STUN/SILENCE adds,
natural expiry, immunity rejection without false frames, and unmapped fixture
kinds without invented presentation.
An isolated real Windows `CreateFileW` read lock reproduces replacement failure
and verifies world ticks and publication recovery after the handle closes.
This verifies the preparation mechanism;
the local client acceptance scenarios remain separate.
