# AI Trading System - GCP VM Deployment

This deployment configuration runs the entire AI Trading System on a single GCP VM with:
- PostgreSQL (with TimescaleDB) for data persistence
- FastAPI backend replacing AWS Lambda handlers
- React dashboard served via Nginx
- WebSocket support for real-time updates
- Cross-cloud access to AWS Bedrock (Claude Opus 4.5) and SageMaker

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        GCP VM                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                     Nginx                            │    │
│  │  - Serves React Dashboard (port 80/443)             │    │
│  │  - Proxies /api/* to FastAPI                        │    │
│  │  - WebSocket proxy for /ws                          │    │
│  │  - Rate limiting & SSL termination                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                   │
│           ┌──────────────┴──────────────┐                   │
│           ▼                              ▼                   │
│  ┌─────────────────┐          ┌─────────────────┐          │
│  │  FastAPI        │          │  React          │          │
│  │  Backend        │          │  Dashboard      │          │
│  │  (port 8000)    │          │  (static)       │          │
│  └────────┬────────┘          └─────────────────┘          │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────┐          ┌─────────────────┐          │
│  │  PostgreSQL     │          │  Redis          │          │
│  │  + TimescaleDB  │          │  (cache)        │          │
│  │  (port 5432)    │          │  (port 6379)    │          │
│  └─────────────────┘          └─────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTPS API calls
                          ▼
              ┌───────────────────────┐
              │        AWS            │
              │  ┌─────────────────┐  │
              │  │ Bedrock         │  │
              │  │ (Claude Opus)   │  │
              │  └─────────────────┘  │
              │  ┌─────────────────┐  │
              │  │ SageMaker       │  │
              │  │ (ML Patterns)   │  │
              │  └─────────────────┘  │
              └───────────────────────┘
```

## Prerequisites

1. GCP VM with:
   - Ubuntu 22.04 LTS (recommended)
   - At least 4 vCPUs, 8GB RAM
   - 50GB SSD storage
   - Docker and Docker Compose installed

2. AWS IAM user with:
   - `bedrock:InvokeModel` permission
   - `sagemaker:InvokeEndpoint` permission

3. GCP Cloud SQL PostgreSQL (optional - can use containerized PostgreSQL)

## Quick Start

1. **Clone the repository to your GCP VM:**
   ```bash
   git clone <your-repo-url>
   cd ai-trading-system/deployment
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   nano .env  # Edit with your values
   ```

3. **Start the services:**
   ```bash
   docker-compose up -d
   ```

4. **Check status:**
   ```bash
   docker-compose ps
   docker-compose logs -f
   ```

5. **Access the dashboard:**
   - Open `http://<your-vm-ip>` in your browser
   - Default login: Create via API or database

## Using GCP Cloud SQL Instead of Containerized PostgreSQL

If you prefer to use GCP Cloud SQL:

1. Create a Cloud SQL PostgreSQL instance with TimescaleDB extension
2. Update `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@/trading?host=/cloudsql/project:region:instance
   ```
3. Remove the `postgres` service from `docker-compose.yml`
4. Configure Cloud SQL Proxy or private IP access

## SSL/HTTPS Setup

1. **Using Let's Encrypt (recommended):**
   ```bash
   # Install certbot
   sudo apt install certbot
   
   # Get certificate
   sudo certbot certonly --standalone -d your-domain.com
   
   # Copy certificates
   sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem deployment/nginx/ssl/
   sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem deployment/nginx/ssl/
   ```

2. **Uncomment HTTPS configuration in `nginx/conf.d/default.conf`**

3. **Restart Nginx:**
   ```bash
   docker-compose restart nginx
   ```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `POST /api/auth/login` | User login |
| `GET /api/news/signals` | Get news signals |
| `GET /api/technical/signals` | Get technical signals |
| `GET /api/strategy/decisions` | Get trade decisions |
| `GET /api/positions/open` | Get open positions |
| `GET /api/risk/portfolio` | Get portfolio risk |
| `WS /ws` | WebSocket for real-time updates |

## Monitoring

- **Logs:** `docker-compose logs -f [service]`
- **PostgreSQL:** Connect via `psql -h localhost -U trading -d trading`
- **Redis:** `docker exec -it trading-redis redis-cli`

## Backup

```bash
# Database backup
docker exec trading-postgres pg_dump -U trading trading > backup.sql

# Restore
cat backup.sql | docker exec -i trading-postgres psql -U trading trading
```

## Scaling Considerations

For higher load:
1. Increase VM size
2. Use GCP Cloud SQL for managed PostgreSQL
3. Use GCP Memorystore for managed Redis
4. Add a load balancer for multiple backend instances

## Troubleshooting

**Backend not starting:**
```bash
docker-compose logs backend
# Check database connection
docker exec trading-backend python -c "from core.database import engine; print('OK')"
```

**WebSocket not connecting:**
- Check Nginx logs: `docker-compose logs nginx`
- Verify WebSocket upgrade headers in browser dev tools

**AWS Bedrock/SageMaker errors:**
- Verify AWS credentials in `.env`
- Check IAM permissions
- Test with AWS CLI: `aws bedrock list-foundation-models`
