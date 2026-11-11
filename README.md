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
