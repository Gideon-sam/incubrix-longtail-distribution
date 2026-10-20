#!/usr/bin/env python3
"""
Ghost bootstrap script — creates Admin API key and saves to shared secrets volume.
Runs after Ghost starts. Uses persistent session with Origin/Referer headers for Ghost 5.
"""
from __future__ import annotations
import os
import time
import httpx
from pathlib import Path

GHOST_URL = os.getenv("GHOST_API_URL", "http://ghost:2368").rstrip("/")
GHOST_EMAIL = os.getenv("GHOST_ADMIN_EMAIL", "incubrix@example.com")
GHOST_PASSWORD = os.getenv("GHOST_PASSWORD", "Incubrix@2024!")
SHARED_KEY_PATH = Path("/run/secrets-shared/ghost_admin_key")
TIMEOUT = 120


def wait_for_ghost():
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        try:
            r = httpx.get(f"{GHOST_URL}/ghost/api/admin/site/", timeout=5)
            if r.status_code in (200, 401):
                print("[INFO] Ghost is ready.")
                return True
        except Exception:
            pass
        print("[INFO] Waiting for Ghost...")
        time.sleep(3)
    print("[WARN] Ghost wait timeout reached — proceeding with fallback key.")
    return False


def setup_and_get_key():
    """Persistent client session to setup Ghost and create integration key."""
    headers = {
        "Origin": GHOST_URL,
        "Referer": f"{GHOST_URL}/ghost/",
        "Accept": "application/json, text/plain, */*",
    }

    with httpx.Client(base_url=GHOST_URL, headers=headers, timeout=30.0) as client:
        # 1. Setup flow
        setup_payload = {
            "setup": [{
                "name": "IncuBrix Admin",
                "email": GHOST_EMAIL,
                "password": GHOST_PASSWORD,
                "blogTitle": "IncuBrix Publication",
            }]
        }
        r_setup = client.post("/ghost/api/admin/authentication/setup/", json=setup_payload)
        if r_setup.status_code in (200, 201):
            print("[INFO] Ghost initial setup completed.")
        elif r_setup.status_code == 422:
            print("[INFO] Ghost already set up.")
        else:
            print(f"[WARN] Ghost setup returned: {r_setup.status_code} {r_setup.text[:150]}")

        # 2. Login (Ghost 5 returns 201 Created on session creation)
        login_payload = {
            "username": GHOST_EMAIL,
            "identification": GHOST_EMAIL,
            "password": GHOST_PASSWORD,
        }
        r_login = client.post("/ghost/api/admin/session/", json=login_payload)
        if r_login.status_code not in (200, 201):
            print(f"[WARN] Ghost session login failed: {r_login.status_code} {r_login.text[:150]}")
            # Try reading directly from Ghost sqlite DB if mounted
            db_candidates = [
                Path("/var/lib/ghost/content/data/ghost.db"),
                Path("/var/lib/ghost/content/data/ghost-dev.db"),
                Path("/var/lib/ghost/content/data/ghost-local.db"),
                Path("/var/lib/ghost/data/ghost.db"),
            ]
            for db_path in db_candidates:
                if db_path.exists():
                    try:
                        import sqlite3
                        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                        cur = conn.cursor()
                        cur.execute("SELECT id, secret FROM api_keys WHERE type='admin' ORDER BY created_at DESC LIMIT 1")
                        row = cur.fetchone()
                        conn.close()
                        if row and row[0] and row[1]:
                            full_key = f"{row[0]}:{row[1]}"
                            _save_key(full_key)
                            print(f"[INFO] Recovered Ghost admin key from sqlite: {full_key[:15]}...")
                            return full_key
                    except Exception as e:
                        print(f"[WARN] Failed sqlite recovery from {db_path}: {e}")
            return ""

        print("[INFO] Ghost session authenticated successfully.")

        # 3. Check existing integrations
        r_list = client.get("/ghost/api/admin/integrations/")
        if r_list.status_code == 200:
            integrations = r_list.json().get("integrations", [])
            for integ in integrations:
                if integ.get("name") == "IncuBrix":
                    for key in integ.get("api_keys", []):
                        if key.get("type") == "admin":
                            full_key = f"{key['id']}:{key['secret']}"
                            _save_key(full_key)
                            return full_key

        # 4. Create integration if not found
        r_create = client.post(
            "/ghost/api/admin/integrations/",
            json={"integrations": [{"name": "IncuBrix"}]},
        )
        if r_create.status_code in (200, 201):
            integration = r_create.json()["integrations"][0]
            for key in integration.get("api_keys", []):
                if key.get("type") == "admin":
                    full_key = f"{key['id']}:{key['secret']}"
                    _save_key(full_key)
                    return full_key

        print(f"[WARN] Failed to create Ghost integration: {r_create.status_code} {r_create.text[:200]}")
        return ""


def _save_key(key: str):
    """Write key to shared volume and local app folder."""
    try:
        SHARED_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHARED_KEY_PATH.write_text(key, encoding="utf-8")
        print(f"[INFO] Saved Ghost admin key to {SHARED_KEY_PATH}")
    except Exception as e:
        print(f"[WARN] Could not save to {SHARED_KEY_PATH}: {e}")

    try:
        Path("/app/.ghost_key").write_text(key, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    is_ready = wait_for_ghost()
    key = ""
    if is_ready:
        time.sleep(2)
        key = setup_and_get_key()
    if not key:
        key = "65f000000000000000000001:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        _save_key(key)
        print(f"[INFO] Using fallback Ghost admin key: {key[:15]}...")
    else:
        print(f"[INFO] GHOST_ADMIN_API_KEY generated: {key[:15]}...")
    print("[INFO] Ghost bootstrap complete.")
