"""
Mock Discourse server — simulates the Discourse REST API.

Runs in Docker as mock-discourse (port 4100).
Used for local certification tests and simulation mode.
All data is stored in memory — resets on restart.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Discourse Server", version="1.0.0")

# In-memory stores
_posts: dict[str, dict] = {}
_topics: dict[str, dict] = {}
_post_counter = 0
_topic_counter = 0

MOCK_API_KEY = "mock_discourse_key"


def _check_auth(request: Request):
    key = request.headers.get("Api-Key", "")
    if key != MOCK_API_KEY:
        raise HTTPException(status_code=401, detail={"error": "Invalid API key"})


@app.post("/posts.json")
async def create_post(request: Request):
    """Create a new topic/post (Discourse POST /posts.json)."""
    global _post_counter, _topic_counter
    _check_auth(request)
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
    return {"status": "ok", "service": "mock-discourse"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4100)
