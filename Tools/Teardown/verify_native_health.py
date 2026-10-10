"""Execute a pinned original ARM64 health helper; compare one production kernel.

No Android, client process, network, code download, or proprietary bytes in Git.
Synthetic buffers and exact dyadic cases qualify this COMPONENT ONLY. A passed
grid is not hit calculation, full-match/client acceptance, or official server parity.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Tools.verification_support import output_directory

BINARY_SHA256 = "cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47"
START, SIZE, STOP = 0xCAA5A0, 0xB4, 0xCAB000
ACTOR, ATTR, OUT = 0x100000, 0x102000, 0x104000


@dataclass(frozen=True)
class Case:
    name: str
    delta: float
    hp: float
    barrier: float
    fortified: float
    flags: int = 0
    expected: tuple | None = None


BRANCH_CASES = (
    Case("healing", 40, 500, 100, 100, expected=(40, 0, 0, 0)),
    Case("zero", 0, 500, 100, 100, expected=(0, 0, 0, 0)),
    Case("unprotected", -100, 500, 0, 0, expected=(-100, 0, 0, 0)),
    Case("barrier_absorbs", -100, 500, 150, 0, expected=(0, 0, -100, 0)),
    Case("barrier_exhausts", -100, 500, 50, 0, expected=(-50, 0, -50, 0)),
    Case("fortified_half", -100, 500, 0, 150, expected=(-50, 0, 0, -50)),
    Case("fortified_exhausts", -100, 500, 0, 20, expected=(-80, 0, 0, -20)),
    Case("both_pools", -150, 500, 30, 40, expected=(-80, 0, -30, -40)),
    Case("fortified_capped_by_hp", -100, 30, 0, 100, expected=(-70, 0, 0, -30)),
    Case("alternate_pool_flag", -100, 500, 0, 0, 4, (0, -100, 0, 0)),
)


def cases(include_grid=False):
    result = list(BRANCH_CASES)
    if include_grid:
        # Exactly representable in float32 throughout this arithmetic:
        # no chosen epsilon hides float64-vs-float32 rounding disagreements.
        values = itertools.product(
            (0.125, 1, 19.375, 100, 255, 400, 10000),
            (0, 0.125, 1, 30, 500),
            (0, 0.125, 50, 150, 600),
            (0, 0.125, 20, 100, 600))
        for index, (damage, hp, barrier, fortified) in enumerate(values):
            result.append(Case(f"dyadic-{index:04d}", -damage, hp, barrier, fortified))
    return result


def validate_case(case):
    for name in ("delta", "hp", "barrier", "fortified"):
        value = getattr(case, name)
        if type(value) not in (int, float):
            raise ValueError(f"{name} must be a finite scalar")
        if name != "delta" and value < 0:
            raise ValueError(f"{name} must be nonnegative")
        try:
            if not math.isfinite(value):
                raise ValueError(f"{name} must be a finite scalar")
            represented = struct.unpack("<f", struct.pack("<f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError(f"{name} exceeds float32 range") from exc
        if represented != value:
            raise ValueError(f"{name} is not exactly representable as float32")
    if type(case.flags) is not int or case.flags not in (0, 4):
        raise ValueError("only the two inspected actor flag cases are qualified")


def load_leaf(binary):
    data = Path(binary).read_bytes()
    if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
        raise ValueError("native library fingerprint differs from the pinned CE 147219 input")
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("expected a little-endian ELF64 AArch64 library")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    stride, count = struct.unpack_from("<HH", data, 54)
    if stride < 56 or phoff + stride * count > len(data):
        raise ValueError("invalid ELF program header table")
    for index in range(count):
        segment = struct.unpack_from("<IIQQQQQQ", data, phoff + index * stride)
        kind, flags, offset, virtual, _, size, _, _ = segment
        if kind == 1 and flags & 1 and virtual <= START and START + SIZE <= virtual + size:
            start = offset + START - virtual
            if start + SIZE > len(data):
                raise ValueError("leaf exceeds its file-backed segment")
            return data[start:start + SIZE]
    raise ValueError("pinned leaf is not inside an executable file-backed PT_LOAD")


class NativeHealth:
    def __init__(self, binary):
        # Lazy optional dependency; wrong inputs never reach instruction execution.
        code = load_leaf(binary)
        import unicorn as uc
        from unicorn import arm64_const as reg
        self.api, self.reg = uc, reg
        self.engine = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
        engine = self.engine
        for address in (START & ~0xFFF, STOP, ACTOR, ATTR, OUT):
            engine.mem_map(address, 0x1000)
        engine.mem_write(START, code)
        engine.mem_protect(START & ~0xFFF, 0x1000, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
        self.context = engine.context_save()
        self.instruction_count, self.writes = 0, set()
        self.allowed_reads = {(ACTOR + 0x40, 8), (ACTOR + 0x301, 2), (ACTOR + 0x303, 1),
                              (ATTR + 0x308, 4), (ATTR + 0x318, 4), (ATTR + 0x31C, 4)}
        engine.hook_add(uc.UC_HOOK_CODE, self.on_code)
        engine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, self.on_memory)

    def on_code(self, engine, address, size, context):
        if not START <= address < START + SIZE:
            raise RuntimeError(f"instruction escaped recovered leaf: {address:#x}")
        self.instruction_count += 1

    def on_memory(self, engine, access, address, size, value, context):
        if access == self.api.UC_MEM_READ:
            if (address, size) not in self.allowed_reads:
                raise RuntimeError(f"unexpected native read: {address:#x}/{size}")
        elif size != 4 or address not in (OUT, OUT + 4, OUT + 8, OUT + 12):
            raise RuntimeError(f"unexpected native write: {address:#x}/{size}")
        else:
            self.writes.add(address)

    def run(self, case):
        validate_case(case)
        engine, reg = self.engine, self.reg
        engine.context_restore(self.context)
        actor, attributes = bytearray(0x1000), bytearray(0x1000)
        struct.pack_into("<Q", actor, 0x40, ATTR)
        actor[0x303] = case.flags
        for offset, value in ((0x308, case.hp), (0x318, case.barrier), (0x31C, case.fortified)):
            struct.pack_into("<f", attributes, offset, value)
        engine.mem_write(ACTOR, bytes(actor))
        engine.mem_write(ATTR, bytes(attributes))
        engine.mem_write(OUT, b"\xFF" * 16)
        for register, value in ((reg.UC_ARM64_REG_X0, ACTOR), (reg.UC_ARM64_REG_X1, OUT),
                                (reg.UC_ARM64_REG_X2, OUT + 4), (reg.UC_ARM64_REG_X3, OUT + 8),
                                (reg.UC_ARM64_REG_X4, OUT + 12), (reg.UC_ARM64_REG_X30, STOP)):
            engine.reg_write(register, value)
        engine.reg_write(reg.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        engine.reg_write(reg.UC_ARM64_REG_FPCR, 0)
        engine.reg_write(reg.UC_ARM64_REG_FPSR, 0)
        engine.reg_write(reg.UC_ARM64_REG_S0, struct.unpack("<I", struct.pack("<f", case.delta))[0])
        self.instruction_count, self.writes = 0, set()
        engine.emu_start(START, STOP, timeout=1_000_000, count=256)
        if engine.reg_read(reg.UC_ARM64_REG_PC) != STOP:
            raise RuntimeError("native leaf did not return within the execution bound")
        if self.writes != {OUT, OUT + 4, OUT + 8, OUT + 12}:
            raise RuntimeError("native leaf did not initialize all four outputs")
        if engine.mem_read(ACTOR, 0x1000) != actor or engine.mem_read(ATTR, 0x1000) != attributes:
            raise RuntimeError("native leaf modified its input buffers")
        raw = bytes(engine.mem_read(OUT, 16))
        if not all(math.isfinite(v) for v in struct.unpack("<4f", raw)):
            raise RuntimeError("native output is not finite")
        return raw


def production_pools(case):
    """Persistent production pools for isolated or sequential aggregate hits."""
    from server.status_effects import StatusEffect, StatusManager, StatusType
    manager = StatusManager()
    for key, kind, amount in (("barrier", StatusType.BARRIER, case.barrier),
                              ("fortified", StatusType.FORTIFIED_HEALTH, case.fortified)):
        if amount:
            manager.apply_effect(StatusEffect(key, kind, 1, 1, 10, 0, 10, amount))
    return manager


def production_split(case):
    """Call the real StatusManager kernel, not a Python copy of the native math."""
    if case.delta > 0 or case.flags != 0:
        return None
    manager = production_pools(case)
    remaining, _ = manager.absorb_damage_with_barrier(1, -case.delta, 1, current_hp=case.hp)
    return (-remaining, 0, manager.get_barrier(1, 1) - case.barrier,
            manager.get_fortified_health(1, 1) - case.fortified)


def float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


SEQUENCES = (
    ("barrier-then-fortified", Case("initial", 0, 500, 40, 120), (20, 40, 100, 300)),
    ("current-hp-cap", Case("initial", 0, 30, 5, 100), (5, 20, 100)),
    ("subunit-pools", Case("initial", 0, 1, .125, .375), (.125, .25, .5, 1)),
)
NON_DYADIC_CASES = (
    Case("decimal-unprotected", -.1, .3, 0, 0),
    Case("decimal-both-pools", -.3, 1, .1, .2),
    Case("decimal-large", -123.456, 789.123, 12.345, 67.89),
    Case("decimal-hp-cap", -100.1, 30.3, .1, 100.7),
    Case("decimal-pool-exhaustion", -.7, .9, .2, .3),
)


def sequential_hits(first, second):
    """Refeed aggregate pools; this does not execute native effect scheduling."""
    sequences, failures = [], []
    for name, initial, damages in SEQUENCES:
        manager = production_pools(initial)
        hp = initial.hp
        native_state = (initial.hp, initial.barrier, initial.fortified)
        rows = []
        for index, damage in enumerate(damages):
            case = Case(f"{name}-{index}", -damage, *native_state)
            raw_a, raw_b = first.run(case), second.run(case)
            output = struct.unpack("<4f", raw_a)
            before = (hp, manager.get_barrier(1, 1), manager.get_fortified_health(1, 1))
            remaining, _ = manager.absorb_damage_with_barrier(1, damage, 1, current_hp=hp)
            production = (-remaining, 0, manager.get_barrier(1, 1) - before[1],
                          manager.get_fortified_health(1, 1) - before[2])
            hp = max(0, hp - remaining)
            # Explicit harness accumulation at native storage precision, not
            # a new rounding policy in the production simulation.
            native_state = tuple(float32(max(0, value + output[offset]))
                                 for value, offset in zip(native_state, (0, 2, 3)))
            production_state = (hp, manager.get_barrier(1, 1), manager.get_fortified_health(1, 1))
            matches = output == production and native_state == production_state
            rows.append({"input": asdict(case), "native": output, "native_hex": raw_a.hex(),
                         "production": production, "native_state_after": native_state,
                         "production_state_after": production_state, "repeat_byte_exact": raw_a == raw_b,
                         "production_exact_numeric_match": matches})
            if raw_a != raw_b or not matches:
                failures.append(case.name)
        sequences.append({"name": name, "initial": asdict(initial), "hits": rows})
    return sequences, failures


def non_dyadic_measurements(first, second):
    """Bounded float32-vs-production observations, NOT an epsilon-based gate.

    Strict NativeHealth.run/validate_case are unchanged. Record explicit input
    quantization separately from arithmetic deltas on equal float32 inputs.
    """
    rows, failures = [], []
    for requested in NON_DYADIC_CASES:
        native_input = replace(requested, **{key: float32(getattr(requested, key))
                                            for key in ("delta", "hp", "barrier", "fortified")})
        raw_a, raw_b = first.run(native_input), second.run(native_input)
        output = struct.unpack("<4f", raw_a)
        production = production_split(requested)
        same_input = production_split(native_input)
        rows.append({"requested_input": asdict(requested), "float32_native_input": asdict(native_input),
                     "native": output, "native_hex": raw_a.hex(), "repeat_byte_exact": raw_a == raw_b,
                     "production_requested_input": production, "production_float32_input": same_input,
                     "native_minus_production": [a - b for a, b in zip(output, production)],
                     "same_input_arithmetic_delta": [a - b for a, b in zip(output, same_input)],
                     "numeric_parity": "MEASURED_ONLY_NOT_QUALIFIED"})
        if raw_a != raw_b:
            failures.append(requested.name)
    return rows, failures


def qualify(binary, include_grid=False):
    started = time.perf_counter()
    selected = cases(include_grid)
    first, second = NativeHealth(binary), NativeHealth(binary)
    rows, failures = [], []
    for case in selected:
        raw_a, raw_b = first.run(case), second.run(case)
        output = struct.unpack("<4f", raw_a)
        production = production_split(case)
        repeatable = raw_a == raw_b
        branch_ok = case.expected is None or output == case.expected
        # Numeric equality is EXACT; signed zero is explicitly not a semantic
        # disagreement. Native-vs-native repeatability above remains byte-exact.
        matches = None if production is None else output == production
        row = {"input": asdict(case), "native": output, "native_hex": raw_a.hex(),
               "repeat_byte_exact": repeatable, "branch_expected_matches": branch_ok,
               "production": production, "production_exact_numeric_match": matches}
        rows.append(row)
        if not repeatable or not branch_ok or matches is False:
            failures.append(case.name)
    sequences, sequence_failures = sequential_hits(first, second)
    measurements, measurement_failures = non_dyadic_measurements(first, second)
    failures.extend(sequence_failures + measurement_failures)
    sequence_rows = [hit for sequence in sequences for hit in sequence["hits"]]
    count = len(rows) + len(sequence_rows) + len(measurements)
    return {
        "status": "FAIL" if failures else "PASS", "scope": "NATIVE_COMPONENT_ONLY",
        "binary": str(Path(binary).resolve()), "binary_sha256": BINARY_SHA256,
        "elf_va": hex(START), "native_bytes": SIZE, "unicorn": first.api.__version__,
        "fpcr": 0, "independent_engines": 2, "registers_and_inputs_reset_between_cases": True,
        "case_count": count, "isolated_case_count": len(rows), "native_executions": 2 * count,
        "production_comparisons": sum(row["production"] is not None for row in rows) + len(sequence_rows),
        "sequential_hit_count": len(sequence_rows), "non_dyadic_measurement_count": len(measurements),
        "sequences": sequences, "non_dyadic_measurements": measurements,
        "non_dyadic_max_abs_delta": max(abs(v) for row in measurements for v in row["native_minus_production"]),
        "repeat_byte_exact": all(row["repeat_byte_exact"] for row in rows + sequence_rows + measurements),
        "failed_cases": failures, "cases": rows, "seconds": time.perf_counter() - started,
        "comparison_policy": "exact numeric equality on dyadic inputs; +0/-0 equivalent; native repeats byte-exact",
        "limits": [
            "Only signed-delta pool splitting; original damage/hit eligibility is an INPUT.",
            "Synthetic buffers, not a game process, actual device or original server executable.",
            "Production comparison covers primary-pool damage with one barrier and one fortified pool, including sequential aggregate hits.",
            "Sequential aggregate accumulation is harness code, not native effect scheduling or death cleanup.",
            "Non-dyadic cases are measurement-only, with input quantization and arithmetic deltas retained; no production rounding policy changed.",
            "Healing, alternate-pool flags, pool expiry/multiple-pool ordering and non-dyadic rounding are not production-qualified here.",
            "No whole-match, smoothness, PvP or independent full-game fidelity acceptance."
        ],
    }


def main(argv=None):
    from server import paths
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path,
                        default=paths.local_root() / "vainglory/lib/arm64-v8a/libGameKindred.so")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--grid", action="store_true", help="add 875 deterministic dyadic production comparisons")
    args = parser.parse_args(argv)
    try:
        output = output_directory(args.output, prefix="halcyon-native-health-")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    manifest_paths = sorted((ROOT / "server").glob("*.py")) + [
        Path(__file__), ROOT / "Tools/verification_support.py"]
    def manifest():
        return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in manifest_paths}
    before = manifest()
    try:
        result = qualify(args.binary, args.grid)
    except (ImportError, FileNotFoundError) as exc:
        result = {"status": "UNAVAILABLE", "scope": "NATIVE_COMPONENT_ONLY", "error": str(exc)}
    except Exception as exc:
        result = {"status": "ERROR", "scope": "NATIVE_COMPONENT_ONLY", "error": repr(exc)}
    result["source_manifest"] = before
    result["workspace_matches_start"] = manifest() == before
    if not result["workspace_matches_start"]:
        result["status"] = "ERROR"
        result["error"] = "authored source changed during qualification"
    (output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("cases", "sequences", "non_dyadic_measurements", "source_manifest")} |
                     {"result": str(output / "result.json")}, indent=2))
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "UNAVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
