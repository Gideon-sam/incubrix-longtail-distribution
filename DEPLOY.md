# Azure Student VM Deployment Guide

## 1. Create Azure VM (Free Student Credits)

In Azure Portal:
- **VM Size:** Standard B2s (2 vCPU, 4 GB RAM) — ~$35/month, well within $100 credit
- **OS:** Ubuntu 22.04 LTS
- **Ports to open in NSG:** 22 (SSH), 8000 (API), 9000 (MinIO, optional)

## 2. Connect and Clone

```bash
ssh azureuser@<YOUR_VM_IP>
git clone https://github.com/YOUR_REPO/incubrix-longtail.git
cd incubrix-longtail
```

## 3. Deploy (One Command)

```bash
chmod +x deploy_azure.sh
./deploy_azure.sh
```

This installs Docker, starts all services, runs smoke tests, and prints your access token.

## 4. Test

```bash
# Health check
curl http://localhost:8000/health

# List connectors (9 registered)
curl http://localhost:8000/api/v1/connectors

# Run the batch smoke tests
docker compose exec api python batch_runner.py \
  --input /app/tests/batch_inputs/ \
  --output /app/tests/batch_results/

# Access dashboard & Swagger docs
# Open in browser: http://<YOUR_VM_IP>:8000/
# Swagger UI:     http://<YOUR_VM_IP>:8000/docs
```

## 5. Run Full Tests

```bash
SIMULATION_MODE=true LLM_PROVIDER=mock \
DATABASE_URL=sqlite+aiosqlite:///./test.db \
REDIS_URL=redis://localhost:6379/99 \
MINIO_ENDPOINT=localhost:9000 \
python -m pytest tests/ -v --tb=short
```

## 6. Switch from Simulation to Real APIs

Edit `.env`:

```env
SIMULATION_MODE=false
DEVTO_API_KEY=your-real-devto-key
GHOST_ADMIN_API_KEY=your-ghost-id:secret
DISCOURSE_API_URL=https://your-discourse-forum.com
LEMMY_API_URL=https://lemmy.world
```

Then restart:
```bash
docker compose restart api
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| API | 8000 | Main FastAPI service |
| PostgreSQL | 5432 | Database (internal) |
| Redis | 6379 | Jobs + idempotency (internal) |
| MinIO | 9000/9001 | Evidence storage |
| Mock Discourse | 4100 | Test Discourse connector |
| Mock Webhook | 4200 | Test HMAC webhook |
| Mock Hashnode | 4300 | Test Hashnode connector |
| Mock PeerTube | 4400 | Test PeerTube connector |
| Lemmy | 8536 | Real Lemmy instance (Docker) |
| Ghost | 2368 | Real Ghost CMS (Docker) |
