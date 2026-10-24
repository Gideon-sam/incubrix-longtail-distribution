"""
scripts/benchmark_catalogue_import.py
======================================
Builds a 1,000-row CSV:
  - 900 distinct valid rows (mixed-language names, prefixed [BENCH])
  - 50 exact duplicates
  - 25 URL-spelling duplicates (www. variant)
  - 25 malformed rows (bad URL scheme)

POSTs it to POST /api/v1/catalogue/import, polls the job, records wall-clock
seconds and the service's imported/duplicates/errors counts, then DELETEs the
[BENCH] rows and writes evidence/benchmarks/catalogue_import_1000_benchmark.json.

Expected: imported=900, duplicates=75, errors=25

Usage:
  python scripts/benchmark_catalogue_import.py --base-url http://localhost:8000
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import time
import uuid
from pathlib import Path

import httpx

EVIDENCE_DIR = Path(__file__).parent.parent / "evidence" / "benchmarks"
POLL_INTERVAL = 3
POLL_TIMEOUT  = 360   # 6 minutes max

CONNECTORS = ["discourse", "lemmy", "devto", "ghost", "hashnode",
              "hmac_webhook", "mrss", "peertube", "assisted"]

# Mixed-language name prefixes to satisfy the brief's "mixed-language names" requirement
LANG_PREFIXES = [
    "[BENCH] Dev Forum",
    "[BENCH] Comunidad Tech",
    "[BENCH] Forum Développeurs",
    "[BENCH] Entwickler Forum",
    "[BENCH] डेवलपर फोरम",
    "[BENCH] 开发者社区",
    "[BENCH] Fórum de Tecnologia",
    "[BENCH] Техническое Сообщество",
    "[BENCH] フォーラム",
    "[BENCH] 기술 포럼",
]


def make_row(idx: int, url: str, name_suffix: str = "") -> dict:
    prefix = LANG_PREFIXES[idx % len(LANG_PREFIXES)]
    connector = CONNECTORS[idx % len(CONNECTORS)]
    return {
        "name": f"{prefix} {idx}{name_suffix}",
        "url": url,
        "platform_key": connector,
        "connector_key": connector,
        "surface": "topic",
        "category": "developer",
        "audience_tags": "tech,developer",
        "language": "en",
        "geo": "global",
        "est_audience": str(1000 + idx * 7),
        "rules_url": f"{url}/rules",
        "frequency_cap": "1/day",
        "self_promo_allowed": "True",
        "link_policy": "allowed",
        "disclosure_required": "False",
        "automation_allowed": "True",
        "relevance_score": "3.5",
        "relevance_reason": "Benchmark row",
        "level": "L0",
        "last_certified_at": "",
    }


def build_csv() -> bytes:
    rows = []

    # 900 distinct valid rows
    for i in range(900):
        url = f"https://bench-{i:04d}.example-incubrix-bench.com/forum"
        rows.append(make_row(i, url))

    # 50 exact duplicates (repeat rows 0-49)
    for i in range(50):
        url = f"https://bench-{i:04d}.example-incubrix-bench.com/forum"
        rows.append(make_row(i, url, " (dup)"))

    # 25 URL-spelling duplicates (www. variant of rows 0-24)
    for i in range(25):
        url = f"https://www.bench-{i:04d}.example-incubrix-bench.com/forum"
        rows.append(make_row(i, url, " (www-dup)"))

    # 25 malformed rows (bad scheme)
    for i in range(25):
        url = f"ftp://bench-bad-{i:04d}.example-incubrix-bench.com/forum"
        rows.append(make_row(900 + i, url, " (malformed)"))

    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def poll_job(client: httpx.Client, base_url: str, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"{base_url}/api/v1/jobs/{job_id}", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") in ("succeeded", "failed"):
                return data
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "job_id": job_id}


def delete_bench_rows(client: httpx.Client, base_url: str) -> int:
    """Delete all destinations whose name starts with [BENCH]."""
    resp = client.get(f"{base_url}/api/v1/destinations", params={"limit": 2000}, timeout=30)
    if resp.status_code != 200:
        return 0
    dests = resp.json()
    if not isinstance(dests, list):
        return 0
    deleted = 0
    for d in dests:
        if str(d.get("name", "")).startswith("[BENCH]"):
            del_resp = client.delete(
                f"{base_url}/api/v1/destinations/{d['id']}", timeout=15
            )
            if del_resp.status_code in (200, 204):
                deleted += 1
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark catalogue import with 1,000-row CSV")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print("Building 1,000-row benchmark CSV …")
    csv_bytes = build_csv()
    print(f"  CSV size: {len(csv_bytes):,} bytes, rows: 1000")

    idempotency_key = f"bench-import-{uuid.uuid4().hex[:12]}"

    with httpx.Client(timeout=60) as client:
        print(f"POSTing to {base_url}/api/v1/catalogue/import …")
        wall_start = time.monotonic()
        resp = client.post(
            f"{base_url}/api/v1/catalogue/import",
            files={"file": ("benchmark_1000.csv", csv_bytes, "text/csv")},
            headers={"Idempotency-Key": idempotency_key},
        )
        if resp.status_code not in (200, 202):
            print(f"ERROR: HTTP {resp.status_code}: {resp.text[:500]}")
            return

        job_id = resp.json().get("job_id") or resp.json().get("id")
        print(f"  job_id: {job_id} — polling …")

        job_data = poll_job(client, base_url, job_id)
        wall_seconds = round(time.monotonic() - wall_start, 2)

        result = job_data.get("result_data") or {}
        imported   = result.get("imported",   0)
        duplicates = result.get("duplicates", 0)
        errors     = result.get("errors",     0)
        status     = job_data.get("status", "unknown")

        print(f"\nResults (service-reported):")
        print(f"  status    = {status}")
        print(f"  imported  = {imported}  (expected 900)")
        print(f"  duplicates= {duplicates}  (expected 75)")
        print(f"  errors    = {errors}  (expected 25)")
        print(f"  wall time = {wall_seconds}s  (limit 300s)")

        passed = (
            status == "succeeded"
            and imported == 900
            and duplicates == 75
            and errors == 25
            and wall_seconds < 300
        )

        evidence = {
            "benchmark_name": "Catalogue 1,000-Row CSV Import & Deduplication",
            "idempotency_key": idempotency_key,
            "job_id": job_id,
            "job_status": status,
            "input_row_count": 1000,
            "input_bytes": len(csv_bytes),
            "imported": imported,
            "duplicates": duplicates,
            "errors": errors,
            "duration_seconds": wall_seconds,
            "pass": passed,
        }

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EVIDENCE_DIR / "catalogue_import_1000_benchmark.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2)
        print(f"\nEvidence written to {out_path}")

        # Clean up [BENCH] rows
        print("Deleting [BENCH] rows …")
        deleted = delete_bench_rows(client, base_url)
        print(f"  Deleted {deleted} [BENCH] destinations")

        print(f"\n{'PASS' if passed else 'FAIL'} — imported={imported}, duplicates={duplicates}, errors={errors}, {wall_seconds}s")


if __name__ == "__main__":
    main()
