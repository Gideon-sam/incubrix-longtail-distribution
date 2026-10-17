"""
Mock Hashnode server — simulates Hashnode GraphQL API.
Runs as mock-hashnode on port 4300.
"""
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Hashnode Server")
_posts: dict[str, dict] = {}


@app.post("/api/graphql")
async def graphql(request: Request):
    body = await request.json()
    query = body.get("query", "")
    variables = body.get("variables", {})

    # Handle publishPost mutation
    if "publishPost" in query or "createPost" in query:
        post_id = str(uuid.uuid4())
        slug = variables.get("input", {}).get("title", "mock-post").lower().replace(" ", "-")[:50]
        _posts[post_id] = {
            "id": post_id, "slug": slug,
            "title": variables.get("input", {}).get("title", "Mock Post"),
            "url": f"https://mock-hashnode.local/@incubrix/{slug}",
            "deleted": False,
        }
        return JSONResponse({"data": {"publishPost": {"post": {
            "id": post_id, "slug": slug,
            "url": f"https://mock-hashnode.local/@incubrix/{slug}"
        }}}})

    # Handle removePost mutation
    if "removePost" in query:
        post_id = variables.get("id", "")
        if post_id in _posts:
            _posts[post_id]["deleted"] = True
        return JSONResponse({"data": {"removePost": {"post": {"id": post_id}}}})

    # Handle post query
    if "post" in query.lower():
        post_id = variables.get("id", "")
        p = _posts.get(post_id)
        if not p or p.get("deleted"):
            return JSONResponse({"data": {"post": None}})
        return JSONResponse({"data": {"post": p}})

    return JSONResponse({"data": {}, "errors": []})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-hashnode"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4300)
