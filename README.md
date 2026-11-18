# India Traffic Intelligence (HTI)

AI-based route planning for locations across India, with traffic analytics and observations currently focused on Hyderabad.

## Technology Stack

- **Frontend**: React + TypeScript + Vite + Tailwind CSS + Leaflet + Recharts
- **Backend**: FastAPI + SQLAlchemy + Pydantic + Pandas + Scikit-learn
- **Database**: SQLite (development) / PostgreSQL (production)
- **ML**: Scikit-learn, XGBoost

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm 9+

### Setup

1. Clone the repository
2. Set up backend: `cd backend && pip install -r requirements.txt`
3. Set up frontend: `cd frontend && npm install`
4. Configure environment variables (see `.env.example`)
5. Run backend: `cd backend && uvicorn app.main:app --reload`
6. Run frontend: `cd frontend && npm run dev`

### Docker deployment

1. Install Docker Desktop (or Docker Engine with Compose).
2. Copy `.env.example` to `.env`. Set a long random alphanumeric `POSTGRES_PASSWORD`, your provider keys, `WEB_PORT`, and the public site origin in `CORS_ORIGINS`.
3. In Google Cloud, enable Maps JavaScript API and Routes API; restrict the browser key to your public HTTPS site origin. Keep `GOOGLE_MAPS_API_KEY` and `GEOAPIFY_API_KEY` as server secrets. Set `VITE_GOOGLE_MAPS_API_KEY` to the same restricted browser key.
4. Run `docker compose up --build -d`.
5. Open `http://localhost:8080` (or your configured `WEB_PORT`). The frontend container serves the built app and proxies `/api` to FastAPI. Put a TLS reverse proxy/load balancer in front of it for a public deployment.

The Compose stack uses PostgreSQL with a persistent volume. Provider based search and traffic features require outbound HTTPS from the backend, valid API keys, and any provider billing/quota setup. GPS requires HTTPS in public deployments. Back up the PostgreSQL volume before upgrades; schema changes are currently initialized with SQLAlchemy `create_all`, not a production migration workflow.

### Separate frontend and backend hosting (for example, Render)

- Deploy the backend as a Python web service with root directory `backend`, build command `pip install -r requirements.txt`, and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Configure backend environment variables: `APP_ENV=production`, `DEBUG=false`, `DATABASE_URL` (a persistent PostgreSQL URL), `GEOAPIFY_API_KEY`, `GOOGLE_MAPS_API_KEY`, and `CORS_ORIGINS` set to the exact frontend origin (for example, `https://your-frontend.onrender.com`).
- Deploy `frontend` as a static site with build command `npm ci && npm run build`, publish directory `dist`, and environment variables `VITE_API_URL=https://your-backend.onrender.com/api` and `VITE_GOOGLE_MAPS_API_KEY`.
- Redeploy the frontend after setting `VITE_API_URL`; Vite embeds it during the build. Open the frontend's URL to use the app. The backend root URL may show a 404 because its API routes live under `/api` and its interactive docs are at `/docs`.

## Project Structure

```
hyderabad-traffic-intelligence/
├── frontend/          # React + TypeScript + Vite
├── backend/           # FastAPI + SQLAlchemy
├── ml/                # Machine learning pipeline
├── database/          # Migrations and schemas
├── data/              # Sample and raw data
└── docs/              # Documentation
```

## Coverage

- **Route planning**: Search and route between Indian cities, addresses, landmarks, and transport hubs.
- **Traffic observations and analytics**: Hyderabad-area data and supported Hyderabad neighborhoods; route planning coverage is not restricted to GHMC.

## License

Educational / Academic Project
