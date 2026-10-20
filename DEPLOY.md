# IncuBrix Long-Tail Distribution Service - Production Azure Deployment Runbook

This runbook outlines the deployment procedure for hosting the IncuBrix Long-Tail Distribution stack on a 24/7 Microsoft Azure Virtual Machine.

---

## 1. Virtual Machine Specifications

Recommended deployment profile for cost efficiency and 24/7 operational stability:

- Target Platform: Microsoft Azure Virtual Machines
- VM Size: Standard B2s (2 vCPUs, 4.0 GiB RAM)
- Operating System: Ubuntu 22.04 LTS (x64 Architecture)
- Disk Storage: 30 GiB Standard SSD (LRS)
- Inbound Ports (NSG): 22 (SSH), 80 (HTTP Web), 443 (HTTPS), 8000 (Direct FastAPI)

---

## 2. Azure Network Security Group (NSG) Configuration

To permit public access from any web browser or client, configure inbound security rules in the Azure Portal:

| Priority | Name | Port | Protocol | Source | Action | Purpose |
|---|---|---|---|---|---|---|
| 300 | AllowSSH | 22 | TCP | Any | Allow | Secure Remote Shell Administration |
| 310 | AllowHTTP | 80 | TCP | Any | Allow | Public Web UI & Nginx Reverse Proxy |
| 320 | AllowHTTPS | 443 | TCP | Any | Allow | Secure Web Traffic (SSL/TLS) |
| 330 | AllowAPI | 8000 | TCP | Any | Allow | Direct FastAPI Service Access |

---

## 3. Azure CLI Provisioning (Alternative to Azure Portal)

To provision the VM via Azure CLI in one automated sequence:

```bash
# 1. Create Resource Group
az group create --name incubrix-rg --location eastus

# 2. Create Virtual Machine with Ubuntu 22.04 LTS
az vm create \
  --resource-group incubrix-rg \
  --name incubrix-vm \
  --image Ubuntu2204 \
  --size Standard_B2s \
  --admin-username azureuser \
  --generate-ssh-keys \
  --public-ip-sku Standard

# 3. Open Inbound Firewall Ports
az vm open-port --resource-group incubrix-rg --name incubrix-vm --port 80 --priority 310
az vm open-port --resource-group incubrix-rg --name incubrix-vm --port 443 --priority 320
az vm open-port --resource-group incubrix-rg --name incubrix-vm --port 8000 --priority 330
```

---

## 4. Host Setup and Automated Deployment

Once connected to your Azure VM via SSH:

```bash
# 1. Connect to the Azure VM
ssh azureuser@<AZURE_VM_PUBLIC_IP>

# 2. Clone the IncuBrix Repository
git clone https://github.com/Gideon-sam/incubrix-longtail-distribution.git
cd incubrix-longtail-distribution

# 3. Execute the Automated Deployment Script
chmod +x deploy_azure.sh
./deploy_azure.sh
```

### Automated Actions Executed by deploy_azure.sh:
1. Configures a 2 GB swapfile to ensure memory stability on 4 GB RAM instances.
2. Installs Docker Engine and the Docker Compose plugin.
3. Automatically generates cryptographically secure keys in .env.
4. Builds and boots all 11 microservices in detached mode.
5. Performs readiness polling against the /ready endpoint.
6. Installs and configures systemd persistence service (incubrix.service) so the stack starts automatically on boot.
7. Installs Nginx reverse proxy routing port 80 to port 8000.
8. Executes the automated batch verification suite.

---

## 5. Ensuring Continuous 24/7 Uptime (Always Run)

The service is managed through systemd:

```bash
# Check service status
sudo systemctl status incubrix.service

# Restart entire stack
sudo systemctl restart incubrix.service

# Stop stack
sudo systemctl stop incubrix.service

# View consolidated container logs
docker compose logs -f api
```

Because `incubrix.service` is enabled in `multi-user.target`, any Azure VM host reboot or scheduled maintenance will automatically restart the Docker Compose stack without administrative intervention.

---

## 6. Accessing the Live Service

Upon completion of the deployment script:

- Production Dashboard: `http://<AZURE_VM_PUBLIC_IP>/dashboard` or `http://<AZURE_VM_PUBLIC_IP>:8000/dashboard`
- Interactive Swagger API Documentation: `http://<AZURE_VM_PUBLIC_IP>/docs`
- Health Liveness Probe: `http://<AZURE_VM_PUBLIC_IP>/health`
- Service Readiness Probe: `http://<AZURE_VM_PUBLIC_IP>/ready`

---

## 7. Production Verification Commands

Run these smoke tests from any terminal:

```bash
# 1. Health Probe
curl -s http://<AZURE_VM_PUBLIC_IP>/health

# 2. Retrieve All 9 Registered Connectors
curl -s http://<AZURE_VM_PUBLIC_IP>/api/v1/connectors

# 3. Execute Batch Test Suite Inside VM
docker compose exec -T api python batch_runner.py \
  --input /app/tests/batch_inputs/ \
  --output /app/tests/batch_results/ \
  --base-url http://localhost:8000
```
