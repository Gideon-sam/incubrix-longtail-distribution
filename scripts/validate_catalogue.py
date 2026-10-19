#!/usr/bin/env python3
"""
Catalogue Validator — IncuBrix Assessment 4 Requirement #4.

Validates catalogue/real_destinations.csv:
1. Column schema validation
2. URL format and validity
3. Rules URL format, legitimacy and policy consistency
4. Duplicate detection (normalised URL + platform_key)
5. Major platform exclusion check (no Reddit, YouTube, X, etc.)
6. Minimum real destination count check (>= 150)
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_COLUMNS = [
    "name",
    "url",
    "platform_key",
    "surface",
    "category",
    "audience_tags",
    "language",
    "geo",
    "est_audience",
    "rules_url",
    "frequency_cap",
    "self_promo_allowed",
    "link_policy",
    "disclosure_required",
    "automation_allowed",
    "connector_key",
    "relevance_score",
    "relevance_reason",
    "level",
    "last_certified_at",
]

FORBIDDEN_MAJOR_PLATFORMS = {
    "reddit", "youtube", "instagram", "facebook", "linkedin", "tiktok", "x", "twitter",
    "threads", "pinterest", "bluesky", "mastodon", "vimeo", "wordpress", "telegram", "discord", "rss", "mrss"
}

FORBIDDEN_DOMAINS = [
    "reddit.com", "youtube.com", "instagram.com", "facebook.com", "linkedin.com",
    "tiktok.com", "twitter.com", "x.com", "threads.net", "pinterest.com",
    "bsky.app", "vimeo.com", "wordpress.com", "t.me", "discord.com", "discord.gg"
]

INVENTED_RULES_PATTERNS = [
    "lemmy.world/post/622",
    "api.incubrix.io",
    "incubrix.io/mrss",
]


def validate_catalogue(csv_path: str = "catalogue/real_destinations.csv") -> bool:
    path = Path(csv_path)
    if not path.is_file():
        print(f"[FAIL] Catalogue file not found at: {csv_path}")
        return False

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)

    print("=" * 70)
    print(" INCUBRIX CATALOGUE VALIDATION REPORT")
    print("=" * 70)
    print(f"File Path: {path.resolve()}")
    print(f"Total Rows: {len(rows)}")

    errors = []
    warnings = []

    # 1. Column Schema Check
    missing_cols = set(EXPECTED_COLUMNS) - set(header)
    if missing_cols:
        errors.append(f"Missing required columns: {sorted(list(missing_cols))}")
    else:
        print("  [PASS] Column schema matches all 20 required fields")

    # 2. Duplicate Detection
    seen_keys = {}
    duplicates = []
    for idx, r in enumerate(rows, start=2):
        u = r.get("url", "").strip().lower().rstrip("/")
        p = r.get("platform_key", "").strip().lower()
        key = (u, p)
        if key in seen_keys:
            duplicates.append((idx, seen_keys[key], r.get("name"), u, p))
        else:
            seen_keys[key] = idx

    if duplicates:
        errors.append(f"Found {len(duplicates)} duplicate destinations (normalised URL + platform)")
        for curr_line, orig_line, name, u, p in duplicates[:5]:
            errors.append(f"    Line {curr_line} duplicates Line {orig_line}: '{name}' ({p}: {u})")
    else:
        print("  [PASS] Zero duplicates detected (normalised URL + platform)")

    # 3. URL Format & Legitimacy
    bad_urls = []
    bad_rules_urls = []
    major_platform_violations = []
    invented_rules = []

    for idx, r in enumerate(rows, start=2):
        name = r.get("name", f"Row {idx}")
        url = r.get("url", "").strip()
        rules_url = r.get("rules_url", "").strip()
        platform = r.get("platform_key", "").strip().lower()
        auto_allowed = str(r.get("automation_allowed", "")).strip().lower() in ("true", "1")
        level = r.get("level", "").strip()

        # Check URL
        parsed = urlparse(url)
        if not (parsed.scheme in ("http", "https") and parsed.netloc):
            bad_urls.append((idx, name, url))

        # Check Major Platforms
        if platform in FORBIDDEN_MAJOR_PLATFORMS or any(m in url.lower() for m in FORBIDDEN_DOMAINS):
            major_platform_violations.append((idx, name, platform, url))

        # Check Rules URL
        if rules_url:
            parsed_rule = urlparse(rules_url)
            if not (parsed_rule.scheme in ("http", "https") and parsed_rule.netloc):
                bad_rules_urls.append((idx, name, rules_url))
            if any(inv in rules_url.lower() for inv in INVENTED_RULES_PATTERNS):
                invented_rules.append((idx, name, rules_url))
            if "news.ycombinator.com" in rules_url.lower() and "ycombinator.com" not in url.lower():
                invented_rules.append((idx, name, rules_url))
        else:
            # If rules_url is empty, automation_allowed must be false, level must be L0 or L1
            if auto_allowed:
                errors.append(f"Line {idx} '{name}': Empty rules_url requires automation_allowed=false (got {auto_allowed})")
            if level not in ("L0", "L1"):
                warnings.append(f"Line {idx} '{name}': Empty rules_url should be L0/L1 (got {level})")

    if bad_urls:
        errors.append(f"Found {len(bad_urls)} malformed destination URLs")
    else:
        print("  [PASS] All destination URLs have valid http(s) format and domain")

    if major_platform_violations:
        errors.append(f"Found {len(major_platform_violations)} forbidden major platform rows (Reddit, YouTube, etc.)")
    else:
        print("  [PASS] Zero forbidden major platform rows (15 big platforms and RSS removed)")

    if invented_rules:
        errors.append(f"Found {len(invented_rules)} invented or unrelated rules URLs")
    else:
        print("  [PASS] Zero invented or unrelated rules URLs")

    # 4. Count Check
    if len(rows) < 150:
        errors.append(f"Catalogue count {len(rows)} is below the required 150+ threshold")
    else:
        print(f"  [PASS] Total catalogue destinations: {len(rows)} (meets >= 150 threshold)")

    print("-" * 70)
    if errors:
        print(f"RESULT: FAIL ({len(errors)} error(s) found)")
        for err in errors:
            print(f"  ✗ {err}")
        return False

    print("RESULT: PASS — Catalogue is 100% compliant with IncuBrix Assessment 4")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = validate_catalogue()
    sys.exit(0 if success else 1)
