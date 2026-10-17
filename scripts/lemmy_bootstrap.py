#!/usr/bin/env python3
"""
Lemmy bootstrap script — creates admin user and test community.
Runs once after the Lemmy container starts. Called by docker-compose init.
Retries until Lemmy is ready (it starts slowly).
"""
import time
import httpx
import os

LEMMY_URL = os.getenv("LEMMY_API_URL", "http://lemmy:8536")
USERNAME = os.getenv("LEMMY_USERNAME", "incubrix_admin")
PASSWORD = os.getenv("LEMMY_PASSWORD", "incubrix_pass")
EMAIL = "incubrix@example.com"
COMMUNITY_NAME = "incubrix_test"

def wait_for_lemmy(timeout=120):
    """Poll until Lemmy's API responds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{LEMMY_URL}/api/v3/site", timeout=5)
            if r.status_code in (200, 400):
                print("✅ Lemmy is ready.")
                return True
        except Exception:
            pass
        print("⏳ Waiting for Lemmy...")
        time.sleep(5)
    raise RuntimeError("Lemmy did not start in time.")

def register_admin():
    """Register the admin user (first user = site admin)."""
    payload = {
        "username": USERNAME,
        "password": PASSWORD,
        "password_verify": PASSWORD,
        "email": EMAIL,
        "show_nsfw": False,
        "answer": None,
    }
    r = httpx.post(f"{LEMMY_URL}/api/v3/user/register", json=payload, timeout=15)
    if r.status_code == 200:
        jwt = r.json().get("jwt", "")
        print(f"✅ Admin user registered. JWT: {jwt[:20]}...")
        return jwt
    # 400 = already registered
    if r.status_code == 400 and "already" in r.text.lower():
        print("ℹ️  Admin user already exists — logging in.")
        r2 = httpx.post(f"{LEMMY_URL}/api/v3/user/login",
                        json={"username_or_email": USERNAME, "password": PASSWORD}, timeout=15)
        return r2.json().get("jwt", "")
    print(f"⚠️  Register response: {r.status_code} {r.text[:200]}")
    return ""

def create_community(jwt: str):
    """Create the test community used for certification."""
    payload = {
        "name": COMMUNITY_NAME,
        "title": "IncuBrix Test Community",
        "description": "Automated certification test community — please ignore.",
        "auth": jwt,
        "nsfw": False,
    }
    r = httpx.post(f"{LEMMY_URL}/api/v3/community", json=payload, timeout=15)
    if r.status_code == 200:
        community_id = r.json()["community_view"]["community"]["id"]
        print(f"✅ Community '{COMMUNITY_NAME}' created. ID: {community_id}")
        return community_id
    # 400 = might already exist
    r2 = httpx.get(f"{LEMMY_URL}/api/v3/community", params={"name": COMMUNITY_NAME}, timeout=15)
    if r2.status_code == 200:
        community_id = r2.json()["community_view"]["community"]["id"]
        print(f"ℹ️  Community already exists. ID: {community_id}")
        return community_id
    print(f"⚠️  Community creation: {r.status_code} {r.text[:200]}")
    return 0

if __name__ == "__main__":
    wait_for_lemmy()
    jwt = register_admin()
    if jwt:
        create_community(jwt)
    print("✅ Lemmy bootstrap complete.")
