# Deployment

One Docker Compose stack on a single Linux VM (GCP e2-standard-2, AWS Lightsail/EC2, Hetzner, etc. — 2 vCPU / 4 GB RAM minimum, 8 GB if you run the IB Gateway).

```
browser ──► web (nginx: dashboard + /api + /ws) ──► backend (FastAPI, 1 worker)
                                                      ├─► postgres (TimescaleDB)
                                                      ├─► redis
                                                      └─► ib-gateway (IBKR paper, optional profile)
```

Only ports 80/443 are published. Postgres, Redis and the IB API port stay on the private Docker network.

## 1. Prepare the VM

```bash
# Ubuntu 22.04/24.04
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
git clone https://github.com/ammartahirr/tradequorum.git && cd tradequorum/deployment
cp .env.example .env && nano .env
```

Firewall: allow inbound 22, 80 and 443 only.

## 2. Secrets (`deployment/.env`)

| Variable | Required | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | `openssl rand -hex 24` |
| `JWT_SECRET_KEY` | yes | `openssl rand -hex 32` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | yes | admin user created on first start |
| `CORS_ORIGINS` | yes | your public URL(s), comma-separated |
| `BROKER` | – | `paper` (simulator, default) or `ibkr` |
| `TWS_USERID`, `TWS_PASSWORD` | for IBKR | the **paper** account login (IBKR Portal → Settings → Paper Trading Account) |
| `IBKR_ACCOUNT` | optional | e.g. `DU1234567` |
| `IBKR_MARKET_DATA_TYPE` | – | `3` delayed (free) / `1` live (needs subscription) |
| `IBKR_ALLOW_LIVE_TRADING` | – | keep `false`; orders are refused on non-`DU` accounts |
| `DEFAULT_DATA_SOURCE` | – | `yahoo` (free), `ibkr`, `synthetic` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | optional | Claude (Bedrock) news analysis; keyword fallback without |
| `SEC_EDGAR_USER_AGENT` | recommended | SEC requires a contact string |
| `REUTERS_API_KEY`, `BLOOMBERG_API_KEY`, `TWITTER_*` | optional | extra news sources |

## 3. Start

```bash
# Simulator broker + Yahoo data (no IBKR needed)
docker compose up -d --build

# With Interactive Brokers paper trading
#   set BROKER=ibkr (and optionally DEFAULT_DATA_SOURCE=ibkr) in .env
docker compose --profile ibkr up -d --build
docker compose logs -f ib-gateway backend     # wait for "Connected to IBKR"
```

Check it:

```bash
curl http://localhost/api/health
curl http://localhost/api/broker/status   # {"broker":"ibkr","connected":true,"paper":true,...}
```

Open `http://<vm-ip>/#/sandbox` and run a backtest.

### IBKR notes
- In TWS/IBKR Portal enable **API access** for the paper account. The container runs IBC, which logs in and keeps the gateway alive (it restarts daily at `AUTO_RESTART_TIME`).
- If your live login uses 2FA, approve the IBKR Mobile prompt when the gateway starts. Paper logins usually don't ask.
- Historical stock data through the API needs market-data permissions. Share your live subscriptions with the paper account (Portal → Settings → Paper Trading → share market data) or keep `DEFAULT_DATA_SOURCE=yahoo`. Forex (IDEALPRO) data is free.
- Only one session per username: logging into TWS elsewhere with the paper user will kick the gateway off.

## 4. HTTPS

Put certificates in `deployment/nginx/ssl/` (`fullchain.pem`, `privkey.pem`, e.g. from `certbot certonly --standalone`) and uncomment the 443 server block in `deployment/nginx/conf.d/default.conf`, then `docker compose up -d --build web`.

## 5. Operate

```bash
docker compose ps
docker compose logs -f backend
docker compose pull && docker compose up -d --build     # update
docker exec trading-postgres pg_dump -U trading trading > backup.sql
```

Database schema is applied only when the Postgres volume is first created. After schema changes on an existing install, run `docker compose down -v` (this destroys data) or apply the changes manually.
