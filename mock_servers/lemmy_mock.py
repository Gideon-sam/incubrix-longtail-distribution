"""
Lightweight Lemmy ActivityPub Mock Server.
Implements Lemmy 0.19.x REST API endpoints for user authentication,
community management, post publishing, status, deletion, and metrics.
"""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Lemmy Mock Server")

_posts: dict[int, dict[str, Any]] = {}
_post_counter = 100
_communities: dict[str, int] = {"incubrix_test": 1}
_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwibmFtZSI6ImluY3Vicml4X2FkbWluIn0.mock_signature"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v3/site")
def get_site():
    return {
        "site_view": {
            "site": {
                "id": 1,
                "name": "IncuBrix Lemmy",
                "sidebar": "IncuBrix ActivityPub Network",
                "published": "2026-01-01T00:00:00Z",
            }
        }
    }


@app.post("/api/v3/user/register")
@app.post("/api/v3/user/login")
async def user_auth(request: Request):
    return {"jwt": _jwt, "registration_created": False, "verify_email_sent": False}


@app.get("/api/v3/community")
def get_community(name: str = "incubrix_test"):
    comm_id = _communities.get(name, 1)
    return {
        "community_view": {
            "community": {
                "id": comm_id,
                "name": name,
                "title": "IncuBrix Test Community",
                "description": "Automated certification community",
                "removed": False,
                "deleted": False,
                "nsfw": False,
                "actor_id": f"http://lemmy:8536/c/{name}",
            }
        }
    }


@app.post("/api/v3/community")
async def create_community(request: Request):
    data = await request.json()
    name = data.get("name", "incubrix_test")
    comm_id = len(_communities) + 1
    _communities[name] = comm_id
    return {
        "community_view": {
            "community": {
                "id": comm_id,
                "name": name,
                "title": data.get("title", name),
                "actor_id": f"http://lemmy:8536/c/{name}",
            }
        }
    }


@app.post("/api/v3/post")
async def create_post(request: Request):
    global _post_counter
    data = await request.json()
    _post_counter += 1
    post_id = _post_counter
    post_obj = {
        "id": post_id,
        "name": data.get("name", "Untitled"),
        "body": data.get("body", ""),
        "creator_id": 1,
        "community_id": data.get("community_id", 1),
        "deleted": False,
        "removed": False,
        "locked": False,
        "published": "2026-10-19T12:00:00Z",
        "ap_id": f"http://lemmy:8536/post/{post_id}",
    }
    _posts[post_id] = post_obj
    return {
        "post_view": {
            "post": post_obj,
            "counts": {"upvotes": 1, "downvotes": 0, "score": 1, "comments": 0},
        }
    }


@app.get("/api/v3/post")
def get_post(id: int = 101):
    post_obj = _posts.get(
        id,
        {
            "id": id,
            "name": "Test Post",
            "body": "Body content",
            "creator_id": 1,
            "community_id": 1,
            "deleted": False,
            "removed": False,
            "locked": False,
            "published": "2026-10-19T12:00:00Z",
            "ap_id": f"http://lemmy:8536/post/{id}",
        },
    )
    return {
        "post_view": {
            "post": post_obj,
            "counts": {"upvotes": 14, "downvotes": 0, "score": 14, "comments": 6},
        }
    }


@app.post("/api/v3/post/delete")
async def delete_post(request: Request):
    data = await request.json()
    post_id = data.get("post_id", 101)
    if post_id in _posts:
        _posts[post_id]["deleted"] = True
    return {
        "post_view": {
            "post": {"id": post_id, "deleted": True, "removed": False},
        }
    }
