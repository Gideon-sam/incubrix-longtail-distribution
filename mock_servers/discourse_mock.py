"""
Mock Discourse server — simulates the Discourse REST API with test controls.

Supports admin switches for Phase 2 hard cases:
- /__admin/drop_response (hangs or times out after creating post)
- /__admin/rate_limit (returns 429 with Retry-After header)
- /__admin/rename_field (renames fields to simulate schema drift)
- /__admin/reset (restores normal operation)
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Discourse Server", version="1.0.0")

# In-memory stores
_posts: dict[str, dict] = {}
_topics: dict[str, dict] = {}
_post_counter = 0
_topic_counter = 0

# Admin testing flags
_hang_next_create = False
_rate_limit_next = False
_rename_field_mode = False
_consecutive_5xx_count = 0

MOCK_API_KEY = "mock_discourse_key"


def _check_auth(request: Request):
    key = request.headers.get("Api-Key", "")
    if key != MOCK_API_KEY:
        raise HTTPException(status_code=401, detail={"error": "Invalid API key"})


@app.post("/__admin/drop_response")
async def admin_drop_response():
    global _hang_next_create
    _hang_next_create = True
    return {"status": "ok", "action": "will_hang_after_create"}


@app.post("/__admin/rate_limit")
async def admin_rate_limit():
    global _rate_limit_next
    _rate_limit_next = True
    return {"status": "ok", "action": "will_rate_limit_once"}


@app.post("/__admin/rename_field")
async def admin_rename_field():
    global _rename_field_mode
    _rename_field_mode = True
    return {"status": "ok", "action": "rename_field_enabled"}


@app.post("/__admin/error_5xx")
async def admin_error_5xx():
    global _consecutive_5xx_count
    _consecutive_5xx_count = 5
    return {"status": "ok", "action": "will_return_5xx_5_times"}


@app.post("/__admin/reset")
async def admin_reset():
    global _hang_next_create, _rate_limit_next, _rename_field_mode, _consecutive_5xx_count
    _hang_next_create = False
    _rate_limit_next = False
    _rename_field_mode = False
    _consecutive_5xx_count = 0
    return {"status": "ok", "action": "reset"}


@app.post("/posts.json")
async def create_post(request: Request):
    """Create a new topic/post (Discourse POST /posts.json)."""
    global _post_counter, _topic_counter, _hang_next_create, _rate_limit_next, _consecutive_5xx_count
    _check_auth(request)

    if _consecutive_5xx_count > 0:
        _consecutive_5xx_count -= 1
        raise HTTPException(status_code=503, detail="Discourse internal error")

    if _rate_limit_next:
        _rate_limit_next = False
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded"},
            headers={"Retry-After": "2", "X-RateLimit-Reset": "2"},
        )

    body = await request.json()

    _topic_counter += 1
    _post_counter += 1
    topic_id = str(_topic_counter)
    post_id = str(_post_counter)

    topic = {
        "id": int(topic_id),
        "title": body.get("title", "Mock Post"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted": False,
    }
    post = {
        "id": int(post_id),
        "topic_id": int(topic_id),
        "raw": body.get("raw", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "like_count": 0,
        "reply_count": 0,
        "reads": 0,
        "deleted": False,
    }
    _topics[topic_id] = topic
    _posts[post_id] = post

    if _hang_next_create:
        _hang_next_create = False
        # Hang longer than client timeout to trigger timeout
        await asyncio.sleep(20)

    # Response schema
    if _rename_field_mode:
        # Schema drift: id renamed to post_identifier
        return JSONResponse(status_code=200, content={
            "post_identifier": int(post_id),
            "topic_identifier": int(topic_id),
            "cooked": body.get("raw", ""),
            "created_at": post["created_at"],
        })

    return JSONResponse(status_code=200, content={
        "id": int(post_id),
        "topic_id": int(topic_id),
        "cooked": body.get("raw", ""),
        "created_at": post["created_at"],
    })


@app.get("/posts/{post_id}.json")
async def get_post(post_id: str, request: Request):
    """Get a post by ID."""
    _check_auth(request)
    post = _posts.get(post_id)
    if not post or post.get("deleted"):
        raise HTTPException(status_code=404, detail={"error": "Not found"})

    if _rename_field_mode:
        return JSONResponse(content={"post_identifier": post["id"], "topic_identifier": post["topic_id"]})

    return JSONResponse(content=post)


@app.delete("/posts/{post_id}.json")
async def delete_post(post_id: str, request: Request):
    """Delete a post."""
    _check_auth(request)
    post = _posts.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail={"error": "Not found"})
    post["deleted"] = True
    return JSONResponse(status_code=200, content={"deleted": True})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-discourse", "posts_count": len(_posts)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4100)
