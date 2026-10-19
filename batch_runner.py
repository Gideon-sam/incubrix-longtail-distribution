#!/usr/bin/env python3
"""
IncuBrix Batch Runner — Integration Standard #10.

Runs a folder or file of JSON test inputs against the API and writes
all results to one output folder.

Usage:
  python batch_runner.py --input tests/batch_inputs/ --output tests/batch_results/ --base-url http://localhost:8000

  python batch_runner.py --input tests/batch_inputs/publish_test.json --output ./results/

Input format (each JSON file or array of objects):
  {
    "method": "POST",
    "path": "/api/v1/publish",
    "headers": {"Idempotency-Key": "test-1"},
    "body": { ... }
  }

Output (written to output folder):
  {filename}_result.json  — HTTP status, response body, timing
  summary.json            — all results with pass/fail
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def run_single(
    client: httpx.AsyncClient,
    base_url: str,
    input_data: dict,
    input_file: str,
) -> dict:
    """Run one test case and return the result."""
    method = input_data.get("method", "POST").upper()
    path = input_data.get("path", "/health")
    headers = input_data.get("headers", {})
    body = input_data.get("body", None)
    expected_status = input_data.get("expected_status", None)

    url = f"{base_url.rstrip('/')}{path}"
    start = time.monotonic()

    try:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, json=body, headers=headers)
        elif method == "PUT":
            resp = await client.put(url, json=body, headers=headers)
        elif method == "DELETE":
            resp = await client.delete(url, headers=headers)
        else:
            return {"error": f"Unsupported method: {method}", "file": input_file}

        elapsed = time.monotonic() - start

        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text

        passed = True
        if expected_status and resp.status_code != expected_status:
            passed = False

        return {
            "file": input_file,
            "method": method,
            "path": path,
            "status_code": resp.status_code,
            "elapsed_ms": round(elapsed * 1000, 1),
            "expected_status": expected_status,
            "passed": passed,
            "response": response_body,
        }

    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "file": input_file,
            "method": method,
            "path": path,
            "status_code": None,
            "elapsed_ms": round(elapsed * 1000, 1),
            "passed": False,
            "error": str(e),
        }


async def run_batch(
    input_path: str,
    output_dir: str,
    base_url: str,
    token: Optional[str] = None,
):
    """Run all test inputs and write results."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all input files
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(input_path.glob("*.json"))
    else:
        print(f"[ERROR] Input path not found: {input_path}")
        return

    print(f"[RUN] Running {len(files)} test file(s) against {base_url}")

    headers = {}
    if token:
        headers["X-Access-Token"] = token

    all_results = []
    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        for file in files:
            with open(file, "r") as f:
                raw = json.load(f)

            # Support single object or array of test cases
            if isinstance(raw, list):
                cases = raw
            else:
                cases = [raw]

            file_results = []
            for i, case in enumerate(cases):
                # Add unique idempotency key if not provided
                if case.get("method", "POST").upper() == "POST":
                    if "headers" not in case:
                        case["headers"] = {}
                    if "Idempotency-Key" not in case["headers"]:
                        case["headers"]["Idempotency-Key"] = f"batch-{file.stem}-{i}-{int(time.time())}"

                result = await run_single(client, base_url, case, file.name)
                file_results.append(result)
                all_results.append(result)

                status = "[PASS]" if result.get("passed", True) else "[FAIL]"
                print(f"  {status} [{result.get('status_code', 'ERR')}] {case.get('method','?')} {case.get('path','?')} ({result.get('elapsed_ms', 0)}ms)")

                if result.get("passed", True):
                    passed += 1
                else:
                    failed += 1

            # Write per-file result
            result_file = output_dir / f"{file.stem}_result.json"
            with open(result_file, "w") as f:
                json.dump(file_results, f, indent=2)

    # Write summary
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "total": len(all_results),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/max(len(all_results),1)*100:.1f}%",
        "results": all_results,
    }
    summary_file = output_dir / "summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[RESULTS] {passed}/{len(all_results)} passed ({summary['pass_rate']})")
    print(f"[OUTPUT] Written to: {output_dir}")
    print(f"[SUMMARY] File: {summary_file}")

    if failed > 0:
        print(f"\n[FAIL] {failed} test(s) failed. Check {summary_file} for details.")
        return 1
    else:
        print("[SUCCESS] All tests passed!")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="IncuBrix Batch Runner — run test inputs against the API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Path to a JSON file or folder of JSON files",
    )
    parser.add_argument(
        "--output", "-o", default="./batch_results",
        help="Output folder (default: ./batch_results)",
    )
    parser.add_argument(
        "--base-url", "-u", default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--token", "-t", default=None,
        help="X-Access-Token for protected demo endpoints",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Request timeout in seconds",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(run_batch(
        input_path=args.input,
        output_dir=args.output,
        base_url=args.base_url,
        token=args.token,
    ))
    raise SystemExit(exit_code or 0)


if __name__ == "__main__":
    main()
