# Fast, scalable nonvisual validation — decision 2026-09-22

## Decision

Use a **reference-driven differential testing workflow**, with three separate
measurement layers. Treat CE as an independent reference with known gaps, not
an infallible oracle. Keep the existing scenario runner and production engine.
No new distributed test service, alternative simulation, image dependency or
translated ARM-hook campaign is needed for this step.

The optimization target is **useful uncertainty removed per minute of scarce
live-client time**. Speed, coverage and confidence are separate measurements;
there is no justified claim of a universally optimal or perfect approach.

```text
Ordinary CE client       Local Halcyon client
  inputs + wire           inputs + wire + authoritative ticks
  logical native state    logical native state
  native replay           native replay when available
             \             /
      immutable external evidence bundles
      identity / build / state / clock qualification
                      |
           semantic offline measurements
                      |
      compatible contracts / explicit unknowns
                      |
        production headless local regression
        reproducible failure -> reduced case
                      |
      targeted client experiment for unresolved behavior
```

### Layer 1 — independent reference preservation

While the external service is available, spend ordinary live sessions on
**missing discriminating cases**, not repeated versions of known walks.
Preserve raw packet data, inputs, anchored native state and native replay in
one hash-manifested external bundle. The native replay alone omits `1070`
corrections; neither server positions nor replay output substitute for client
positions. No arbitrary packet injection, headless swarm or backend probing.

Each bundle must distinguish observed versus missing context: client/library
build, match/connection, EID/slot/hero/team, initial position, rank/items,
HP/resources, speed/buffs, target identity, scripted input boundaries and
clock brackets. Unknown speed/buff or network conditions block a claim of a
controlled cross-service comparison, not extraction of narrower valid facts.
Archive the original data before normalization; never fabricate missing inputs.

Prioritize shared 3v3 contracts: movement/retarget/arrival/corners, basic attack
and death, common resources/items, then wave/turret/jungle/respawn/end-game.
Acquire evidence that multiple heroes depend on before duplicating per-hero
work. Time-sensitive dependent actions stay inside the existing scripts.

### Layer 2 — cheap local diagnosis and regression

Reuse `SnapshotStream.advance_simulation` and `Tools/run_scenarios.py` for
fixed-tick production tests. Reproduce known inputs from declared initial
state; compare local event/state streams exactly. This is not remote-state
reconstruction: a client capture timestamp does not disclose the remote
server's execution tick, hidden state or full input history.

Use independent fixtures through the existing semantic-reference interface
only when required initial conditions and expected metrics are established.
Do not automatically turn observed CE reversal counts into desired behavior,
or relabel descriptive client measurements as `VERIFIED` reference fixtures.

For locally reproduced failures, minimize the intent/state difference while
retaining the same failure predicate. Failed setup or a missing prerequisite
must be `UNRESOLVED`, not evidence that removal fixed the bug. Delta debugging
supports this reduction strategy; it does not promise a globally smallest
case. See [Zeller and Hildebrandt's primary paper](https://www.st.cs.uni-saarland.de/papers/tse2002/).
This minimizer is a **next implementation**, not a shipped feature.

Add bounded, reproducible input generation and conditional invariants where
independent outputs are unavailable: valid walkable route segments, no motion
after stop absent external forces, actor attribution, reconnect continuity.
Test generation may be seeded; authoritative gameplay remains deterministic.
Do not declare arbitrary route progress monotonic across retargets or corners.

Differential testing compares independent implementations to expose semantic
disagreement, not to prove that one is always right. The method is supported
by [the Csmith authors' primary paper](https://users.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf);
applying it to Halcyon requires the explicit state/time qualification above.

### Layer 3 — client behavior and delivery conditions

Use the actual CE client only for behavior the server cannot establish:
prediction, correction application, presentation state and UI/input acceptance.
Current read-only registry/position access is qualified on LDPlayer; keep it.
The next observation gap is the model/scene transform and consumption timing,
using a concrete consumer/component anchor, not broad scanning or screenshots.

For latency sensitivity, eventually run declared delivery profiles **locally**
and keep them distinct from a measured CE condition. CE request-to-ack spans
187–214 ms here, but that is not enough to derive one-way delay, jitter or the
server-processing component. Do not invent a "matched CE latency" profile.
No controlled-latency runner is claimed shipped by this decision.

## Approaches compared against current evidence

| Approach | Benefit | Limitation | Decision |
|---|---|---|---|
| Repeated live sessions with ad-hoc analysis | Real client/service | Entry and observation setup consumed several failed windows | Reserve live time for new information |
| Replay-only reference | Convenient retained semantics | 45 owner corrections absent from 15,041 replay frames | Complementary input only |
| Headless-only testing | Fast production regression | Cannot establish native correction or model behavior | Primary local regression, not sole acceptance |
| Independent data + production replay + targeted native reads | Reusable evidence, causal local tests, real client state | Requires explicit state/clock/coverage gates | **Selected** |
| Move immediately to new hardware/hooks | Might expose other runtime APIs | Current anchored reads already work; migration is unqualified | Only if a named remaining accessor requires it |
| New cloud/distributed analytics stack | Potential large-corpus throughput | No measured need; current batch is seconds | Defer until profiling justifies it |

## Implemented now: reusable offline client measurement

`Tools/Teardown/inspect_movement_trace.py trace --timing --client-run ...`
joins existing wire data to one successful movement scenario. Its helper is
`Tools/Teardown/movement_client_report.py`; this is an inspector extension,
not another scenario execution path. It does not contact a client/backend or
load the navmesh. Reuse decoded wire rows for multiple runs in a batch.

It corroborates owner/slot/hero from native metadata, scenario identity and
wire bootstrap. It validates sample counts/completeness, start/end clock
brackets, finite values and gesture/request attribution. Sample windows end
before the **next scripted gesture**, not its later wire receipt, and trim
the observed clock-alignment envelope and reads spanning the next input.
It retains source hashes, clock
quality, sample gaps and read duration. These are not FPS measurements.

Only explicitly supplied `--straight-walk <label>` entries receive backward
projection metrics. Arbitrary corners remain `UNMEASURED`; missing accepted
targets cannot produce a reversal verdict. The `0.0001`-unit discriminator
is not a perception/smoothness threshold. Output remains `MEASURED`, with
client smoothness and cross-run comparability explicitly `UNVERIFIED`.

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace <wire.jsonl> --connection <verified-id> --timing --eid <verified-eid> --slot <verified-slot> --client-run <existing-run-directory> --straight-walk C-to-A-0 --straight-walk A-to-C-0
python -B -m unittest server.test.test_movement_client_report server.test.test_movement_timing
```

### Demonstrated offline result

**7 retained runs / 47 real inputs / 27,323 client samples in 3.49 seconds**
including three wire sources, measurement and report/hash writing, on this
host. This is one observed run, not a general scaling benchmark. Per-run
analysis was 82–329 ms. No new live interaction or simulation was performed.

| Retained run | Straight legs with backward steps |
|---|---:|
| Baseline A1 | 6/6 |
| Suppressed B | 0/6 |
| Baseline A2 | 2/6 |
| Production patched local | 0/6 |
| External CE | 6/6 |
| Local/CE broad corner batteries | Not evaluated by straight-line discriminator |

The stricter clock-boundary trimming reproduced the prior findings. This
does not turn the unequal-latency CE/local comparison into a controlled A/B.
**20 focused tests pass**, including ten new offline measurement tests;
the existing inspector CLI also reproduced the CE short-run result. A final
read-boundary qualification rerun reproduced all counts in 2.40 seconds;
filesystem caching was not controlled, so these are spot timings, not a
throughput guarantee.

Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/differential-workflow-b284bc1449c6490db80482ef5601d921/`.
`offline-batch.json`, per-run reports, `analyze_retained.py`,
`cli-ce-short.json` and source/preservation manifests. Raw source bundles
remain in the prior movement/reference evidence directories linked from
[navigation](solo-sandbox-navigation.md).

## Next work in dependency order

1. Qualify missing initial state/resource/buff fields and durable nonvisual
   entry readiness, so a service session can run several useful scenarios
   without reasoning round trips or guessed UI state.
2. Turn qualified **independent** semantic observations into the existing
   fixture interface, with narrowly stated compatibility. Current movement
   reports are measurements, not that fixture qualification.
3. Reproduce remaining route-quality and correction cases in production;
   reduce a repeatable failure before adding more cases.
4. Close model-transform/consumption observation and controlled local delivery
   tests before expanding smoothness claims to realistic network conditions.
5. Scale CPU-only production batches; add a content-hash cache/index only when
   measured corpus-read/analysis cost warrants it. Keep one runtime owner per
   emulator. Do not spend concurrency on conflicting live-client control.
