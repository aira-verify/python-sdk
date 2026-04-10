"""Real benchmark of Aira's cryptographic primitives.

Measures the deterministic operations Aira uses to mint and verify
receipts. No LLM, no network, no database. Reproducible on any machine
with `pip install cryptography`.

Usage:
    python scripts/benchmark.py

These are the same primitives the Aira backend uses to mint receipts.
Numbers will vary by machine — we publish the ones from our reference
hardware on the landing page.
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import statistics
import time
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)


# ── Sample payload (typical agent action) ──
SAMPLE_PAYLOAD: dict[str, Any] = {
    "agent_id": "agent_lending_001",
    "action_type": "loan_decision",
    "details": "Approved €200,000 loan for customer C-4521. Credit score 742, annual income €85,000, debt €12,000.",
    "model_id": "claude-sonnet-4-6",
    "timestamp": "2026-04-10T11:24:00Z",
    "metadata": {
        "ip": "10.0.1.42",
        "user_id": "user_admin_001",
        "session_id": "sess_a8f3c1e7",
    },
}


# ── Aira's signing primitives (matches backend exactly) ──

def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sha256_hash(data: str) -> str:
    """SHA-256 hash of a string, returned as hex."""
    return hashlib.sha256(data.encode()).hexdigest()


# Generate a fresh signing key for the benchmark
_private_key = Ed25519PrivateKey.generate()
_public_key_bytes = _private_key.public_key().public_bytes(
    Encoding.Raw, PublicFormat.Raw
)
_public_key_b64 = base64.b64encode(_public_key_bytes).decode()


def sign_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Sign a canonical JSON payload. Returns (payload_hash, signature_b64url)."""
    canonical = canonical_json(payload)
    payload_hash = sha256_hash(canonical)
    signature_bytes = _private_key.sign(canonical.encode())
    signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode()
    return f"sha256:{payload_hash}", f"ed25519:{signature_b64}"


def verify_signature(payload: dict[str, Any], signature_b64url: str) -> bool:
    """Verify an Ed25519 signature against the public key."""
    try:
        sig_data = signature_b64url.removeprefix("ed25519:")
        signature_bytes = base64.urlsafe_b64decode(sig_data)
        _private_key.public_key().verify(
            signature_bytes, canonical_json(payload).encode()
        )
        return True
    except Exception:
        return False


# ── Rules engine (same logic as backend) ──

_OPS = {
    "eq": lambda a, e: a == e,
    "ne": lambda a, e: a != e,
    "gt": lambda a, e: a is not None and a > e,
    "lt": lambda a, e: a is not None and a < e,
    "gte": lambda a, e: a is not None and a >= e,
    "lte": lambda a, e: a is not None and a <= e,
    "in": lambda a, e: a in (e or []),
    "not_in": lambda a, e: a not in (e or []),
    "contains": lambda a, e: e in (a or ""),
}


def evaluate_rules(conditions: list[dict], context: dict) -> bool:
    """All conditions must match (AND logic)."""
    if not conditions:
        return True
    for cond in conditions:
        field = cond.get("field")
        op = cond.get("op", "eq")
        expected = cond.get("value")
        actual = context.get(field)
        if not _OPS.get(op, lambda a, e: False)(actual, expected):
            return False
    return True


SAMPLE_POLICY_CONDITIONS = [
    {"field": "action_type", "op": "eq", "value": "loan_decision"},
    {"field": "amount", "op": "gt", "value": 100_000},
    {"field": "country", "op": "in", "value": ["DE", "FR", "AT", "IT"]},
]

SAMPLE_CONTEXT = {
    "action_type": "loan_decision",
    "amount": 200_000,
    "country": "DE",
    "agent_id": "agent_001",
}


# ── Benchmark harness ──

def bench(name: str, fn: Callable[[], object], iterations: int = 10_000) -> dict:
    """Run a function N times, return latency stats in microseconds."""
    for _ in range(100):
        fn()  # warm-up

    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1000)

    samples.sort()
    return {
        "name": name,
        "iterations": iterations,
        "p50_us": samples[len(samples) // 2],
        "p95_us": samples[int(len(samples) * 0.95)],
        "p99_us": samples[int(len(samples) * 0.99)],
        "mean_us": statistics.mean(samples),
        "min_us": samples[0],
        "max_us": samples[-1],
    }


def fmt_us(us: float) -> str:
    if us < 1:
        return f"{us * 1000:.1f}ns"
    if us < 1000:
        return f"{us:.2f}μs"
    return f"{us / 1000:.2f}ms"


def fmt_throughput(p50_us: float) -> str:
    if p50_us == 0:
        return "∞"
    ops_per_sec = 1_000_000 / p50_us
    if ops_per_sec >= 1_000_000:
        return f"{ops_per_sec / 1_000_000:.2f}M ops/s"
    if ops_per_sec >= 1_000:
        return f"{ops_per_sec / 1_000:.1f}K ops/s"
    return f"{ops_per_sec:.0f} ops/s"


def print_result(r: dict) -> None:
    print(f"\n{r['name']}")
    print(f"  iterations: {r['iterations']:,}")
    print(f"  p50:        {fmt_us(r['p50_us']):>10}")
    print(f"  p95:        {fmt_us(r['p95_us']):>10}")
    print(f"  p99:        {fmt_us(r['p99_us']):>10}")
    print(f"  mean:       {fmt_us(r['mean_us']):>10}")
    print(f"  throughput: {fmt_throughput(r['p50_us']):>10}")


def main() -> None:
    print("=" * 60)
    print("Aira primitives benchmark")
    print("=" * 60)
    print(f"\nMachine: {platform.machine()} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    print(f"Sample payload size: {len(canonical_json(SAMPLE_PAYLOAD))} bytes")

    results = []

    results.append(
        bench("canonical_json (deterministic serialization)",
              lambda: canonical_json(SAMPLE_PAYLOAD))
    )

    canonical = canonical_json(SAMPLE_PAYLOAD)
    results.append(
        bench("sha256_hash (payload fingerprint)",
              lambda: sha256_hash(canonical))
    )

    results.append(
        bench("sign_payload (Ed25519 + SHA-256, full receipt mint)",
              lambda: sign_payload(SAMPLE_PAYLOAD))
    )

    payload_hash, signature = sign_payload(SAMPLE_PAYLOAD)
    results.append(
        bench("verify_signature (Ed25519 verification)",
              lambda: verify_signature(SAMPLE_PAYLOAD, signature))
    )

    results.append(
        bench("evaluate_rules (3-condition policy match)",
              lambda: evaluate_rules(SAMPLE_POLICY_CONDITIONS, SAMPLE_CONTEXT))
    )

    def end_to_end():
        if evaluate_rules(SAMPLE_POLICY_CONDITIONS, SAMPLE_CONTEXT):
            sign_payload(SAMPLE_PAYLOAD)

    results.append(
        bench("end-to-end (rules eval + receipt mint, in-process)",
              end_to_end)
    )

    for r in results:
        print_result(r)

    print("\n" + "=" * 60)
    print("Headline numbers (p50)")
    print("=" * 60)
    for r in results:
        print(f"  {r['name'][:50]:50} {fmt_us(r['p50_us']):>10}  {fmt_throughput(r['p50_us']):>14}")
    print()

    print("\nJSON summary:")
    print(json.dumps(
        {r["name"]: {"p50_us": round(r["p50_us"], 3), "p95_us": round(r["p95_us"], 3), "p99_us": round(r["p99_us"], 3)} for r in results},
        indent=2,
    ))


if __name__ == "__main__":
    main()
