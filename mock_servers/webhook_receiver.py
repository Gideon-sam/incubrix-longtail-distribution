"""
HMAC Webhook receiver mock — verifies X-IncuBrix-Signature and stores payloads.
Runs as mock-webhook on port 4200.
"""
import hashlib
import hmac
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Webhook Receiver")
_received: dict[str, dict] = {}
SECRET = "webhook_secret_key"


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.body()
    sig_header = request.headers.get("X-IncuBrix-Signature", "")
    # Correct: use hmac.new() from the hmac module
    mac = hmac.new(SECRET.encode(), body, hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    if not hmac.compare_digest(sig_header, expected):
        raise HTTPException(status_code=401, detail={"error": "Invalid signature"})
    payload = json.loads(body)
    post_id = request.headers.get("X-IncuBrix-PostId", "unknown")
    _received[post_id] = payload
    return JSONResponse(status_code=200, content={"received": True, "post_id": post_id})


@app.get("/webhook/posts/{post_id}")
async def get_post(post_id: str):
    if post_id not in _received:
        raise HTTPException(status_code=404, detail={"error": "Not found"})
    return _received[post_id]


@app.delete("/webhook/posts/{post_id}")
async def delete_post(post_id: str):
    """Certification cleanup — delete the test post."""
    if post_id in _received:
        del _received[post_id]
        return {"deleted": True}
    raise HTTPException(status_code=404, detail={"error": "Not found"})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-webhook", "total_received": len(_received)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4200)
