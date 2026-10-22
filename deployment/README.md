# deployment/

Docker Compose stack for the API server, dashboard, database and (optional) Interactive Brokers gateway.

| Path | Purpose |
|---|---|
| `docker-compose.yml` | postgres, redis, backend, web (nginx + dashboard), `ib-gateway` (profile `ibkr`) |
| `Dockerfile.backend` | FastAPI app + shared `src/` engine (build context = repo root) |
| `Dockerfile.frontend` | Vite build served by nginx (build context = repo root) |
| `backend/` | FastAPI app (`main.py`, `api/routes`, `services`) |
| `database/schema.sql` | applied on first Postgres start |
| `nginx/` | reverse proxy config |
| `.env.example` | all secrets/config, copy to `.env` |

```bash
cp .env.example .env            # fill in
docker compose up -d --build    # add --profile ibkr for IB Gateway
```

Full guide: [../DEPLOYMENT.md](../DEPLOYMENT.md).

## Local development without Docker

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r deployment/backend/requirements.txt
cd deployment/backend
PYTHONPATH=../.. BROKER=paper ENABLE_SCHEDULER=false uvicorn main:app --reload --port 8000

cd ../../dashboard && npm ci
VITE_API_URL=http://localhost:8000/api VITE_WS_URL=ws://localhost:8000/ws npm run dev
```

The sandbox (`/#/sandbox`) works without Postgres. Login, orders and positions need the database.
