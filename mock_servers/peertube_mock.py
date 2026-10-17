"""Mock PeerTube server on port 4400."""
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock PeerTube Server")
_videos: dict[str, dict] = {}
MOCK_KEY = "mock_peertube_key"


def _auth(request: Request):
    auth = request.headers.get("Authorization", "")
    if MOCK_KEY not in auth:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized"})


@app.post("/api/v1/videos/upload")
async def upload_video(request: Request):
    _auth(request)
    vid_id = str(uuid.uuid4())
    _videos[vid_id] = {"id": vid_id, "name": "Mock Video", "url": f"http://mock-peertube:4400/videos/watch/{vid_id}", "deleted": False}
    return JSONResponse({"video": {"id": vid_id, "uuid": vid_id, "shortUUID": vid_id[:8]}})


@app.get("/api/v1/videos/{video_id}")
async def get_video(video_id: str, request: Request):
    _auth(request)
    v = _videos.get(video_id)
    if not v or v.get("deleted"):
        raise HTTPException(status_code=404, detail={"error": "Not found"})
    return JSONResponse(v)


@app.delete("/api/v1/videos/{video_id}")
async def delete_video(video_id: str, request: Request):
    _auth(request)
    if video_id in _videos:
        _videos[video_id]["deleted"] = True
    return JSONResponse({"deleted": True})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-peertube"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4400)
