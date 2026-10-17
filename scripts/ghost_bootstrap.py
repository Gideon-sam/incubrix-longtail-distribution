#!/usr/bin/env python3
"""
Ghost bootstrap script — creates Admin API key and saves to .env.
Runs after Ghost starts. Ghost auto-creates a default key on first run.
We read the key from the database via the Ghost CLI or first-setup flow.
"""
import time
import httpx
import os
import json

GHOST_URL = os.getenv("GHOST_API_URL", "http://ghost:2368")
TIMEOUT = 120

def wait_for_ghost():
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        try:
            r = httpx.get(f"{GHOST_URL}/ghost/api/admin/site/", timeout=5)
            if r.status_code in (200, 401):
                print("✅ Ghost is ready.")
                return True
        except Exception:
            pass
        print("⏳ Waiting for Ghost...")
        time.sleep(5)
    raise RuntimeError("Ghost did not start in time.")

def setup_ghost():
    """Run Ghost first-time setup to get an admin key."""
    setup_payload = {
        "setup": [{
            "name": "IncuBrix Admin",
            "email": "incubrix@example.com",
            "password": "Incubrix@2024!",
            "blogTitle": "IncuBrix Test Blog",
        }]
    }
    r = httpx.post(f"{GHOST_URL}/ghost/api/admin/authentication/setup/",
                   json=setup_payload, timeout=30)
    if r.status_code == 200:
        print("✅ Ghost setup complete.")
    elif r.status_code == 422:
        print("ℹ️  Ghost already set up.")
    else:
        print(f"⚠️  Ghost setup: {r.status_code} {r.text[:200]}")

def get_admin_token():
    """Login to get a session token, then create API key."""
    # Login
    r = httpx.post(f"{GHOST_URL}/ghost/api/admin/session/",
                   json={"username": "incubrix@example.com", "password": "Incubrix@2024!"},
                   timeout=15)
    if r.status_code != 200:
        print(f"⚠️  Ghost login failed: {r.status_code} {r.text[:100]}")
        return ""

    session_cookie = r.headers.get("Set-Cookie", "")

    # Create an integration (gets Admin API key)
    headers = {"Cookie": session_cookie, "Content-Type": "application/json"}
    r2 = httpx.post(
        f"{GHOST_URL}/ghost/api/admin/integrations/",
        json={"integrations": [{"name": "IncuBrix"}]},
        headers=headers, timeout=15
    )
    if r2.status_code == 201:
        integration = r2.json()["integrations"][0]
        api_key = next(
            (k["secret"] for k in integration.get("api_keys", []) if k["type"] == "admin"),
            ""
        )
        key_id = next(
            (k["id"] for k in integration.get("api_keys", []) if k["type"] == "admin"),
            ""
        )
        full_key = f"{key_id}:{api_key}"
        print(f"✅ Ghost Admin API key created: {full_key[:20]}...")
        # Write to env file for other services to read
        with open("/app/.ghost_key", "w") as f:
            f.write(full_key)
        return full_key
    print(f"⚠️  Ghost integration creation: {r2.status_code} {r2.text[:200]}")
    return ""

if __name__ == "__main__":
    wait_for_ghost()
    setup_ghost()
    time.sleep(2)
    key = get_admin_token()
    if key:
        print(f"GHOST_ADMIN_API_KEY={key}")
    print("✅ Ghost bootstrap complete.")
