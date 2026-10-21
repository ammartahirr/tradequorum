# AI Trading System - GCP VM Deployment Guide

Complete step-by-step guide to deploy the AI Trading System on a Google Cloud Platform VM.

## Prerequisites

- GCP account with billing enabled
- Local machine with SSH access
- All API keys ready (AWS, Exness MT5, News APIs)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      GCP VM (Ubuntu 22.04)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Docker Compose                    │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐ │   │
│  │  │  Nginx  │  │ Backend │  │Postgres │  │ Redis  │ │   │
│  │  │  :80    │──│  :8000  │──│  :5432  │  │ :6379  │ │   │
│  │  │  :443   │  │ FastAPI │  │TimescaleDB│ │        │ │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └────────┘ │   │
│  │       │            │                                │   │
│  │       │      ┌─────┴─────┐                         │   │
│  │       │      │    src/   │ (Trading Logic)         │   │
│  │       │      └───────────┘                         │   │
│  │  ┌────┴────┐                                       │   │
│  │  │Frontend │ (React Dashboard)                     │   │
│  │  └─────────┘                                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │   AWS    │   │  Exness  │   │  News    │
        │ Bedrock  │   │   MT5    │   │  APIs    │
        │SageMaker │   │          │   │          │
        └──────────┘   └──────────┘   └──────────┘
```

---

## Part 1: Create GCP VM

### 1.1 Create VM Instance via GCP Console

```bash
# Or use gcloud CLI:
gcloud compute instances create ai-trading-vm \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=100GB \
  --boot-disk-type=pd-ssd \
  --tags=http-server,https-server
```

Recommended specs:
- Machine type: e2-standard-4 (4 vCPU, 16 GB RAM) or higher
- Boot disk: 100 GB SSD
- OS: Ubuntu 22.04 LTS

### 1.2 Configure Firewall Rules

```bash
# Allow HTTP
gcloud compute firewall-rules create allow-http \
  --allow tcp:80 \
  --target-tags=http-server

# Allow HTTPS
gcloud compute firewall-rules create allow-https \
  --allow tcp:443 \
  --target-tags=https-server
```

### 1.3 Reserve Static IP (Optional but Recommended)

```bash
gcloud compute addresses create ai-trading-ip --region=us-central1

# Attach to VM
gcloud compute instances delete-access-config ai-trading-vm \
  --access-config-name="external-nat" --zone=us-central1-a

gcloud compute instances add-access-config ai-trading-vm \
  --access-config-name="external-nat" \
  --address=$(gcloud compute addresses describe ai-trading-ip --region=us-central1 --format='value(address)') \
  --zone=us-central1-a
```

---

## Part 2: Connect to VM

### 2.1 SSH into VM

```bash
# Using gcloud
gcloud compute ssh ai-trading-vm --zone=us-central1-a

# Or using standard SSH (get external IP from console)
ssh -i ~/.ssh/your-key username@EXTERNAL_IP
```

---

## Part 3: Install Dependencies on VM

### 3.1 Update System

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.2 Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group (logout/login required)
sudo usermod -aG docker $USER

# Start Docker service
sudo systemctl enable docker
sudo systemctl start docker
```

### 3.3 Install Docker Compose

```bash
# Install Docker Compose v2
sudo apt install docker-compose-plugin -y

# Verify installation
docker compose version
```

### 3.4 Install Additional Tools

```bash
# Install useful tools
sudo apt install -y git curl wget nano htop
```

### 3.5 Logout and Login Again

```bash
# Required for docker group to take effect
exit
# Then SSH back in
gcloud compute ssh ai-trading-vm --zone=us-central1-a
```

---

## Part 4: Transfer Project Files

### 4.1 On Your Local Machine - Package Files

```bash
# Navigate to project root
cd /path/to/ai-trading-system

# Create deployment package (only required folders)
tar -czvf ai-trading.tar.gz \
  deployment/ \
  dashboard/ \
  src/ \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='dist' \
  --exclude='.git'
```

### 4.2 Transfer to VM

```bash
# Using gcloud SCP
gcloud compute scp ai-trading.tar.gz ai-trading-vm:~ --zone=us-central1-a

# Or using standard SCP
scp -i ~/.ssh/your-key ai-trading.tar.gz username@EXTERNAL_IP:~
```

### 4.3 On VM - Extract Files

```bash
# Create project directory
mkdir -p ~/ai-trading-system
cd ~/ai-trading-system

# Extract files
tar -xzvf ~/ai-trading.tar.gz

# Verify structure
ls -la
# Should show: deployment/  dashboard/  src/
```

---

## Part 5: Configure Environment

### 5.1 Create Environment File

```bash
cd ~/ai-trading-system/deployment

# Copy example env file
cp .env.example .env

# Edit with your secrets
nano .env
```

### 5.2 Required Environment Variables

Edit `.env` and fill in ALL these values:

```bash
# ============ DATABASE ============
POSTGRES_PASSWORD=your_very_secure_password_here

# ============ JWT (generate with: openssl rand -hex 32) ============
JWT_SECRET_KEY=your_generated_jwt_secret

# ============ AWS CREDENTIALS ============
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=us-east-1

# ============ EXNESS MT5 ============
MT5_LOGIN=12345678
MT5_PASSWORD=your_mt5_password
MT5_SERVER=Exness-MT5Real

# ============ NEWS APIS (at least one required) ============
TWITTER_BEARER_TOKEN=your_twitter_bearer_token
# REUTERS_API_KEY=your_reuters_key
# BLOOMBERG_API_KEY=your_bloomberg_key
# NEWSAPI_KEY=your_newsapi_key

# ============ ENCRYPTION (generate with: openssl rand -hex 32) ============
ENCRYPTION_KEY=your_generated_encryption_key

# ============ ADMIN USER ============
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=your_secure_admin_password
```

### 5.3 Generate Secure Keys

```bash
# Generate JWT secret
openssl rand -hex 32

# Generate encryption key
openssl rand -hex 32

# Generate database password
openssl rand -base64 24
```

---

## Part 6: SSL Certificate Setup (Optional but Recommended)

### 6.1 Install Certbot

```bash
sudo apt install certbot -y
```

### 6.2 Get SSL Certificate

```bash
# Stop any service on port 80 first
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com
```

### 6.3 Copy Certificates

```bash
# Create SSL directory
mkdir -p ~/ai-trading-system/deployment/nginx/ssl

# Copy certificates (requires sudo)
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ~/ai-trading-system/deployment/nginx/ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ~/ai-trading-system/deployment/nginx/ssl/
sudo chown $USER:$USER ~/ai-trading-system/deployment/nginx/ssl/*
```

### 6.4 Update Nginx Config for SSL

Edit `deployment/nginx/conf.d/default.conf` to enable HTTPS (uncomment SSL section).

---

## Part 7: Deploy Application

### 7.1 Build and Start Services

```bash
cd ~/ai-trading-system/deployment

# Build all images
docker compose build

# Start all services in detached mode
docker compose up -d
```

### 7.2 Verify Services are Running

```bash
# Check all containers
docker compose ps

# Expected output:
# NAME                 STATUS
# trading-postgres     Up (healthy)
# trading-redis        Up (healthy)
# trading-backend      Up (healthy)
# trading-frontend     Up
# trading-nginx        Up
```

### 7.3 Check Logs

```bash
# All logs
docker compose logs

# Specific service logs
docker compose logs backend
docker compose logs postgres
docker compose logs nginx

# Follow logs in real-time
docker compose logs -f backend
```

### 7.4 Verify Database Schema

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U trading -d trading

# Check schema was created
\dn
# Should show: aitrading

# Check tables
\dt aitrading.*

# Exit
\q
```

---

## Part 8: Verify Deployment

### 8.1 Test API Health

```bash
# From VM
curl http://localhost/api/health

# Expected: {"status": "healthy", ...}
```

### 8.2 Test from Browser

Open in browser:
- Dashboard: `http://YOUR_VM_IP/`
- API Docs: `http://YOUR_VM_IP/api/docs`

### 8.3 Test WebSocket

```bash
# Install wscat for testing
npm install -g wscat

# Test WebSocket connection
wscat -c ws://localhost/ws
```

---

## Part 9: Management Commands

### 9.1 Stop Services

```bash
cd ~/ai-trading-system/deployment
docker compose down
```

### 9.2 Restart Services

```bash
docker compose restart

# Restart specific service
docker compose restart backend
```

### 9.3 Update Application

```bash
# Pull latest code (if using git)
git pull

# Or transfer new files via SCP

# Rebuild and restart
docker compose build
docker compose up -d
```

### 9.4 View Resource Usage

```bash
# Container stats
docker stats

# System resources
htop
```

### 9.5 Database Backup

```bash
# Backup database
docker compose exec postgres pg_dump -U trading trading > backup_$(date +%Y%m%d).sql

# Restore database
cat backup_20240101.sql | docker compose exec -T postgres psql -U trading trading
```

### 9.6 Clean Up Docker

```bash
# Remove unused images
docker image prune -a

# Remove unused volumes (CAUTION: deletes data)
docker volume prune

# Full cleanup
docker system prune -a
```

---

## Part 10: Monitoring & Maintenance

### 10.1 Set Up Log Rotation

```bash
# Docker handles log rotation, but configure limits
# Edit /etc/docker/daemon.json
sudo nano /etc/docker/daemon.json
```

Add:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
```

```bash
# Restart Docker
sudo systemctl restart docker
```

### 10.2 Set Up Auto-Restart on Boot

```bash
# Docker Compose services already have restart: unless-stopped
# Ensure Docker starts on boot
sudo systemctl enable docker
```

### 10.3 Set Up SSL Certificate Auto-Renewal

```bash
# Add cron job for certbot renewal
sudo crontab -e

# Add this line:
0 0 1 * * certbot renew --quiet && docker compose -f /home/$USER/ai-trading-system/deployment/docker-compose.yml restart nginx
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs <service-name>

# Check if ports are in use
sudo lsof -i :80
sudo lsof -i :5432
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check PostgreSQL logs
docker compose logs postgres

# Test connection
docker compose exec postgres psql -U trading -d trading -c "SELECT 1"
```

### Backend Errors

```bash
# Check backend logs
docker compose logs backend

# Enter backend container for debugging
docker compose exec backend bash
```

### Out of Disk Space

```bash
# Check disk usage
df -h

# Clean Docker
docker system prune -a

# Check large files
du -sh /* | sort -h
```

### Memory Issues

```bash
# Check memory
free -h

# Check container memory usage
docker stats --no-stream
```

---

## Quick Reference Commands

```bash
# Start everything
cd ~/ai-trading-system/deployment && docker compose up -d

# Stop everything
docker compose down

# View logs
docker compose logs -f

# Restart backend
docker compose restart backend

# Enter PostgreSQL
docker compose exec postgres psql -U trading -d trading

# Enter backend shell
docker compose exec backend bash

# Check status
docker compose ps

# Rebuild after code changes
docker compose build && docker compose up -d
```

---

## Security Checklist

- [ ] Changed all default passwords in `.env`
- [ ] Generated secure JWT_SECRET_KEY
- [ ] Generated secure ENCRYPTION_KEY
- [ ] Set up SSL certificates
- [ ] Configured firewall (only 80/443 open)
- [ ] Set up regular database backups
- [ ] Enabled log rotation
- [ ] Restricted SSH access (key-only, no root)

---

## Support

For issues:
1. Check logs: `docker compose logs`
2. Verify `.env` configuration
3. Ensure all required API keys are valid
4. Check GCP firewall rules
