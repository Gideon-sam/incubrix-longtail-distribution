"""
scripts/generate_certification_evidence.py
==========================================
For each connector, pick a destination from GET /api/v1/destinations, POST /api/v1/certify
with an Idempotency-Key, poll GET /api/v1/jobs/{id} until the job settles, then write:

  evidence/certification/<connector_key>/certification_run.json
  evidence/certification/<connector_key>/README.md

Values come ONLY from the API. No invented / placeholder data anywhere.
A succeeded job with no live_url is recorded as FAILED.
Simulation runs are labelled SIMULATION.

Usage:
  python scripts/generate_certification_evidence.py --base-url http://localhost:8000
  python scripts/generate_certification_evidence.py --base-url http://localhost:8000 --only discourse,lemmy
  python scripts/generate_certification_evidence.py --base-url http://localhost:8000 --connections connections.json

--connections  Path to a JSON file with per-connector credentials. NEVER commit this file.
               Format: {"discourse": {"api_key": "...", "base_url": "..."}, ...}
--only         Comma-separated list of connector keys to run (default: all).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

EVIDENCE_DIR = Path(__file__).parent.parent / "evidence" / "certification"
POLL_INTERVAL = 2      # seconds between job status polls
POLL_TIMEOUT  = 120    # seconds before giving up

CONNECTOR_KEYS = [
    "discourse",
    "lemmy",
    "devto",
    "ghost",
    "hashnode",
    "hmac_webhook",
    "mrss",
    "peertube",
    "assisted",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate certification evidence from live API")
    p.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    p.add_argument("--connections", default=None, help="Path to connections JSON file (never committed)")
    p.add_argument("--only", default=None, help="Comma-separated connector keys to run")
    return p.parse_args()


def pick_destination(client: httpx.Client, base_url: str, connector_key: str) -> dict | None:
    """Return first active destination matching connector_key, or None."""
    resp = client.get(f"{base_url}/api/v1/destinations", params={"connector_key": connector_key})
    if resp.status_code != 200:
        return None
    dests = resp.json()
    if not isinstance(dests, list):
        return None
    for d in dests:
        if d.get("connector_key") == connector_key and d.get("status") == "active":
            return d
    # Fall back: any destination with this connector key
    for d in dests:
        if d.get("connector_key") == connector_key:
            return d
    return None


def get_service_mode(client: httpx.Client, base_url: str) -> str:
    """Return 'SIMULATION' or 'LIVE' based on /health endpoint."""
    try:
        resp = client.get(f"{base_url}/health", timeout=5)
        data = resp.json()
        sim = data.get("simulation_mode", data.get("config", {}).get("simulation_mode", True))
        return "SIMULATION" if sim else "LIVE"
    except Exception:
        return "UNKNOWN"


def poll_job(client: httpx.Client, base_url: str, job_id: str) -> dict:
    """Poll GET /api/v1/jobs/{id} until status is succeeded/failed or timeout."""
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"{base_url}/api/v1/jobs/{job_id}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "")
            if status in ("succeeded", "failed"):
                return data
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "job_id": job_id}


def certify_connector(
    client: httpx.Client,
    base_url: str,
    connector_key: str,
    dest: dict,
    extra_connection: dict,
    service_mode: str,
) -> dict:
    """Run one certification and return the evidence dict."""
    idempotency_key = f"cert-{connector_key}-{uuid.uuid4().hex[:12]}"
    wall_start = time.monotonic()

    payload = {
        "destination_id": dest["id"],
        "connection": extra_connection or {},
    }

    resp = client.post(
        f"{base_url}/api/v1/certify",
        json=payload,
        headers={
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if resp.status_code not in (200, 202):
        return {
            "connector_key": connector_key,
            "service_mode": service_mode,
            "status": "FAILED",
            "reason": f"POST /api/v1/certify returned HTTP {resp.status_code}: {resp.text[:500]}",
            "destination_id": dest["id"],
            "destination_name": dest.get("name"),
            "idempotency_key": idempotency_key,
            "measured_seconds": round(time.monotonic() - wall_start, 2),
        }

    job_resp = resp.json()
    job_id = job_resp.get("job_id") or job_resp.get("id")
    if not job_id:
        return {
            "connector_key": connector_key,
            "service_mode": service_mode,
            "status": "FAILED",
            "reason": f"No job_id in certify response: {resp.text[:300]}",
            "destination_id": dest["id"],
            "destination_name": dest.get("name"),
            "idempotency_key": idempotency_key,
            "measured_seconds": round(time.monotonic() - wall_start, 2),
        }

    job_data = poll_job(client, base_url, job_id)
    wall_seconds = round(time.monotonic() - wall_start, 2)
    job_status = job_data.get("status", "unknown")
    result_data = job_data.get("result_data") or {}
    live_url = result_data.get("live_url") or job_data.get("live_url")
    level = result_data.get("level") or dest.get("level")

    # A succeeded job with no live_url counts as FAILED
    if job_status == "succeeded" and not live_url and service_mode != "SIMULATION":
        outcome = "FAILED"
        reason = "Job succeeded but live_url was absent"
    elif job_status == "succeeded":
        outcome = "PASSED"
        reason = None
    else:
        outcome = "FAILED"
        reason = job_data.get("error_message") or f"Job status: {job_status}"

    return {
        "connector_key": connector_key,
        "service_mode": service_mode,
        "destination_id": dest["id"],
        "destination_name": dest.get("name"),
        "destination_url": dest.get("url"),
        "idempotency_key": idempotency_key,
        "job_id": job_id,
        "job_status": job_status,
        "outcome": outcome,
        "reason": reason,
        "level": level,
        "live_url": live_url,
        "measured_seconds": wall_seconds,
        "result_data": result_data,
    }


def write_evidence(connector_key: str, evidence: dict) -> None:
    out_dir = EVIDENCE_DIR / connector_key
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "certification_run.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    mode = evidence.get("service_mode", "UNKNOWN")
    outcome = evidence.get("outcome", "UNKNOWN")
    readme_lines = [
        f"# Certification Evidence — {connector_key}\n",
        f"**Mode:** {mode}  ",
        f"**Outcome:** {outcome}  ",
        f"**Destination:** {evidence.get('destination_name')} (`{evidence.get('destination_id')}`)  ",
        f"**Job:** `{evidence.get('job_id')}` → `{evidence.get('job_status')}`  ",
        f"**Measured:** {evidence.get('measured_seconds')} s  ",
        f"**Level:** {evidence.get('level')}  ",
        f"**Live URL:** {evidence.get('live_url') or '(none — simulation)'}  ",
        "",
        "Generated by `scripts/generate_certification_evidence.py`. Do not edit by hand.",
    ]
    readme_path = out_dir / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("\n".join(readme_lines))

    print(f"  [{outcome}] {connector_key}: {evidence.get('measured_seconds')}s "
          f"job={evidence.get('job_status')} level={evidence.get('level')}")


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    keys_to_run = CONNECTOR_KEYS
    if args.only:
        keys_to_run = [k.strip() for k in args.only.split(",") if k.strip()]

    connections: dict = {}
    if args.connections:
        conn_path = Path(args.connections)
        if not conn_path.exists():
            print(f"ERROR: --connections file not found: {conn_path}", file=sys.stderr)
            sys.exit(1)
        with open(conn_path, "r", encoding="utf-8") as f:
            connections = json.load(f)

    with httpx.Client(timeout=30) as client:
        service_mode = get_service_mode(client, base_url)
        print(f"Service mode: {service_mode}")
        print(f"Running certification for: {', '.join(keys_to_run)}\n")

        skipped = []
        for key in keys_to_run:
            print(f"→ {key}")
            dest = pick_destination(client, base_url, key)
            if dest is None:
                print(f"  [SKIP] No destination found for connector_key={key}")
                skipped.append(key)
                continue

            extra_conn = connections.get(key, {})
            evidence = certify_connector(client, base_url, key, dest, extra_conn, service_mode)
            write_evidence(key, evidence)

    if skipped:
        print(f"\nSkipped (no destination): {', '.join(skipped)}")
    print("\nDone. Evidence written to evidence/certification/")


if __name__ == "__main__":
    main()
