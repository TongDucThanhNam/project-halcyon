# Research spikes

> Throwaway code that *validates* claims in the design documents. Not
> shipped, not built, not loaded by Unity. Git-tracked for review because
> it carries evidence labels that pair with the design doc findings.
>
> **Rule:** spikes live here, not under `Assets/_Game/Scripts/Runtime/`.
> A spike that survives more than two design rounds must graduate out
> into its own goal file and implementation folder, with tests, before
> it can be cited as a feature of Veilbound.

| Spike | Purpose | Pairing doc |
|---|---|---|
| `determinism/` | Validate `DeterministicRuleEngine` contract — two Python processes write byte-identical snapshots given the same intent log | [veilbound-multiplayer-design.md §10 step 2](../../veilbound-multiplayer-design.md), [veilbound-multiplayer-spike-report.md](../../veilbound-multiplayer-spike-report.md) |

## determinism/

Three files:

| File | Role |
|---|---|
| `engine.py` | `DeterministicRuleEngine` reference — trig + division + lerp paths |
| `run_process.py` | `host` and `peer` roles, both run the engine, write snapshots |
| `verify.py` | Byte-compare host and peer snapshots, locate first divergence |

Reproduce:

```bash
python engine.py                         # self-check (one process, two intents)
python run_process.py host 60            # writes intent log + host snapshots
python run_process.py peer 60            # reads intent log, writes peer snapshots
python verify.py                         # byte-compare; exit 0=PASS, 1=FAIL, 2=missing
```

Outcomes documented in `veilbound-multiplayer-spike-report.md` §3 (positive
case) and §4 (negative case). Both verified on 2026-09-03.
