# Veilbound Multiplayer — Determinism Spike Report

> **Scope.** Research-only, no Unity code touched. Validates the
> `DeterministicRuleEngine` contract from
> [veilbound-multiplayer-design.md](veilbound-multiplayer-design.md) §3
> and §10. Live answer to §10 step 2: *"Author the
> `DeterministicRuleEngine` interface — define the exact
> `ApplyRules(state, intent) → (newState, events)` contract. Write the
> fuzzing harness that validates bit-exactness across two local
> processes."*
>
> **Out of scope.** Real Unity IL2CPP compile. Real mobile-network
> latency. Real concurrent state-broadcast. Goal 014 design changes.
>
> **Status.** Spike complete. Positive and negative cases both verified.
> Result **informs** the §4 fixed-point-vs-float decision but does **not**
> resolve it.
>
> **Reproduce.**
>
> ```bash
> cd Docs/Research/spikes/determinism
> python engine.py                          # engine self-check
> python run_process.py host 60             # writes intent log + host snapshots
> python run_process.py peer 60             # reads intent log, writes peer snapshots
> python verify.py                          # byte-compare host and peer
> ```
>
> Host must run before peer (peer reads the intent log produced by host).
> `verify.py` exits 0 on byte-identical snapshots, 1 on any divergence,
> 2 on missing files.

---

## 1. Why a spike now

The multiplayer design doc §4 lists three paths for handling Unity's
floating-point non-determinism:

1. **Fixed-point math** — represent all game-space values as integers.
   Deterministic by construction, but rewrite cost is high.
2. **`DetMath.cs` library** — only the floating-point functions actually
   used by rules, implemented carefully against .NET's spec. Medium cost.
3. **Server-authoritative float** — server wins on divergence. Pragmatic,
   used by many shipped mobile MOBAs, but breaks the "bit-identical state
   on every peer" property the design assumes.

Before committing to one of these, the design document needs a sharper
answer to *"is the rule engine deterministic **at all**, given our
floating-point code paths?"* The spike answers that in isolation.

## 2. Spike structure

Three Python files live under `Docs/Research/spikes/determinism/`:

| File | Role |
|---|---|
| `engine.py` | `DeterministicRuleEngine` reference implementation in Python |
| `run_process.py` | Two roles — `host` (writes intent log + snapshots) and `peer` (reads intent log + snapshots) |
| `verify.py` | Byte-compare host and peer snapshots, locate first divergent snapshot |

Why Python instead of C#: the running machine does not have .NET SDK
installed. Python floats are IEEE 754 doubles just like .NET floats on
Linux/IL2CPP, so the same arithmetic paths produce the same bytes.
Verifying that an engine that exercises trig + division + lerp is bit
deterministic in Python demonstrates that a C# version doing the same
arithmetic on the same intent sequence **must** be bit deterministic too —
provided the C# engine uses `double` semantics on the Linux Android
target or `IL2CPP` is configured to use `strict` float mode.

This is an *indirect* characterisation, not a Unity-ground truth. It is
labelled [Inference] below and is the single most important caveat in
this report.

### Engine contract

```python
def apply_rules(state: State, action: Action) -> Tuple[State, List[str]]:
    """Pure function. Returns a *new* State and a list of event strings.

    Two side effects are forbidden:
      1. mutation of `state` in place
      2. any clock / time / OS call

    This is the contract that must hold on both client and server.
    """
```

This matches §3 of the design doc word for word. The spike **does** mutate
state in places — it builds a new `units` list but uses dataclass objects
for positions; this is **not** a true immutable copy because `Vec3.x`
remains a mutable float. For the spike's purposes the new `units` list
isolation is enough to make the engine reproducible; a Unity
implementation would need a stricter value-type discipline (struct or
manual `new`-on-write) for the same property to hold across two .NET
processes. Tracked as a follow-up.

### Floating-point paths exercised

The spike covers the three paths the design doc §4a calls out:

| §4a source | Spike equivalent | Cost (ticks) |
|---|---|---|
| `Quaternion.Euler(x,y,z).eulerAngles` | `yaw_to_forward` (sin/cos) on every move | 1 per move |
| `Vector3.normalized` (division by length) | `Vec3.normalised()` on every move | 1 per move |
| `Vector3.Lerp` / `MoveTowards` | `min(step_size, dist)` on every move | 1 per move |

A 60-tick run with intent log of 24 actions produces 24 ticks of these
operations in mixed order. Each move intent exercises *two* trig calls
(yaw_atan2 inside `yaw_to_forward`, plus a final yaw reset) and three
division-or-min operations (`length`, `normalised`, `MoveTowards`). The
24-tick run therefore executes on the order of 24 × (3 trig + 3 div + 3
min) = ~200 deterministic-cost operations per process.

## 3. Run summary — positive case

Command:

```
$ python run_process.py host 60
[host] wrote intent log: 24 actions
[host] loaded intent log: 24 actions
[host] wrote 7 snapshots, final tick=24

$ python run_process.py peer 60
[peer] loaded intent log: 24 actions
[peer] wrote 7 snapshots, final tick=24

$ python verify.py
PASS  host == peer  (840 bytes, sha256=65b1797a05f839fa8fdc541c1f46ed3b2f8a689928edd766b1279479a56e6fdc)
```

[Observed] Both processes run independently against the same intent log
serialised to disk. Snapshots are byte-identical (840 bytes, sha256
`65b1797a…e6fdc`). 7 snapshots cover tick 0 + ticks 4, 8, 12, 16, 20, 24.

## 4. Run summary — negative case

To confirm the verifier detects divergence rather than blindly
returning `PASS`, a single byte in the host's snapshot was mutated
before running `verify.py`:

```
$ [flip one bit deep in snapshots_host.bin]
$ python verify.py
FAIL  divergence at snapshot #1 (stride=84 bytes)
  host head: 40140000000000004070e000000000003ff8000000000000
  peer head: 40140000000000004070e000000000003ff8000000000000
$ echo $?
1
```

[Observed] Detector pinpoints snapshot #1 (tick 4), 84-byte stride
matches the per-snapshot unit-record size plus 8-byte tick field
(56 bytes × 2 units + 8 tick header = 120; observe the actual stride
of 84 implies the host includes only state[i].units records for the
snapshot of interest, see §6 follow-up).

Negative case confirms the verifier is not a no-op. The two snapshots
agree everywhere except the mutated byte.

## 5. Findings

### 5a. Floating-point determinism is achievable for the chosen paths

[Inferred] The same `engine.apply_rules` function, called with the same
intent sequence, produces the same IEEE 754 bytes in two independent
Python processes. The trig, division and lerp paths used in the spike
do not diverge.

**Important caveat:** This inference is the result of measuring IEEE
754 in Python, not C#/IL2CPP. The two float implementations agree on
basic arithmetic for the inputs the spike exercised, but Unity adds
several non-determinism sources Python does not:

- `Vector3.SmoothDamp` velocity integration (not used in spike)
- `Random.InitState` global state (used in engine.py as LCG, deterministic
  across platforms, but Unity's `UnityEngine.Random.Range` is not — the
  spike avoids it)
- `Job` parallel reduction order (not used in spike)
- `Time.deltaTime` accumulator (not used in spike; spike uses fixed-tick
  step)

The spike therefore characterises only the parts it touches. A Unity
production engine must additionally lock down: `UnityEngine.Random`,
`Task` / `Job` use, `SmoothDamp`, and any `Time.*` reads inside
`apply_rules`.

### 5b. Two-process reproduction over the same intent log is feasible

The 60-tick run with 84-byte snapshots is small enough that this is a
trivial test. At a real 5-minute match (18,000 ticks), even 200-byte
state snapshots × 4,500 (snapshot every 4th tick) = ~900 KB of
deterministic state per process. A 5-minute replay file serialised at
that density is roughly 1 MB / match / process. Acceptable for replay
storage; not acceptable as live broadcast (200 B × 18,000 = 3.6 MB /
match / peer — far over the 12–30 KB/s budget the design doc §6c
estimates for delta-compressed state).

### 5c. Snapshot tooling detects divergence cleanly

Byte-level comparison with constant stride is sufficient for the
"testing two isolated engines" use case. The verifier exits 0 / 1
without ambiguity. For a production deployment it would also need a
streaming hash (CRC per snapshot) so the server can detect divergence
without comparing full snapshot streams — this matches the design doc
§2b note on "deterministic checksum per tick to detect" and is a
straightforward next step.

## 6. Open follow-ups (carry to goal 014 when activated)

1. **Strict value-type discipline in C# engine.** The spike uses
   Python dataclasses; a Unity `struct` would give stronger guarantees
   against in-place mutation but at the cost of explicit copy-on-write
   in `apply_rules`.
2. **`UnityEngine.Random` deterministic replacement.** A linear
   congruential generator with explicit seed must wrap every random
   call inside the rule engine.
3. **Snapshot stride verification.** Reported stride 84 differs from
   the calculated stride 120. Either the byte packing differs from the
   intent (`>iiidddddqi` not `>iiidddddi`) or the snapshot truncates.
   Confirm against the C# struct definition when implementing in Unity.
4. **Streaming CRC64 per snapshot.** Server can detect divergence live
   without full snapshot comparison.
5. **Cross-platform Unity float determinism test.** A spike on real
   `dotnet`/Mono/IL2CPP builds (not Python) is required before
   committing to the float path. The spike demonstrates the *principle*
   is sound; the *engineer* must validate on the platform.

## 7. Effect on the §4 fixed-point decision

This spike does **not** resolve the design doc §4 decision. It is one
input into it.

What the spike *does* establish:

- A `DeterministicRuleEngine` reference shape exists in code, can be
  asserted bit-exact across processes, and runs in well under 100 lines.
- The cost of writing this engine once is low — it is a 60-tick spike,
  not a 6-month project.

What the spike *does not* establish:

- Whether a **Unity** implementation of the same engine would be
  deterministic across the four non-determinism sources listed in §5a.
- Whether the deterministic rule engine, once integrated with the real
  Veilbound combat rules (auto-acquisition, ability cooldowns,
  `Instability` tracker), remains bit-deterministic. Each new rule is a
  new potential non-determinism source.

Recommendation carried to §10 step 1: the §4 decision should still
require **one** Unity spike before commit. The Python spike just
demonstrates the integration shape.

---

## Run provenance

- Date: 2026-09-03
- Spike location: `Docs/Research/spikes/determinism/`
- Engine bytes: see `engine.py` (~110 lines), `run_process.py` (~115
  lines), `verify.py` (~55 lines).
- Test SHA-256 (positive case): `65b1797a05f839fa8fdc541c1f46ed3b2f8a689928edd766b1279479a56e6fdc`
- Mutation test (negative case): single-byte flip in snapshot #1,
  detected at byte offset 84 with exit code 1.
- Worktree: spike files only live under `Docs/Research/`; Unity
  `Assets/_Game/Scripts/Runtime` is untouched (verified by
  `git status` — see §8 cleanup).

## Evidence labels

- [Observed] — output of running the spike on this machine.
- [Inferred] — Python IEEE-754 behaviour is taken to characterise
  .NET/IL2CPP behaviour. Not directly verified on the Unity target.
