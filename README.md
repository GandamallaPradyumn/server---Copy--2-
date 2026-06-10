# TSRTC Operational Insights Server

An AI-powered backend system for **Telangana State Road Transport Corporation (TSRTC)** that provides intelligent KPI analysis, driver operations monitoring, and actionable depot management insights — built with FastAPI, Streamlit, Groq LLM, and MySQL.

---

## 🚀 What This Project Does

This server powers a multi-role dashboard platform for TSRTC depot operations. It enables:

- **Depot Managers (DM)** and **Regional Managers (RM)** to monitor driver KPIs across their depots
- **Admins** to upload, transform, and manage operational data via an ETL pipeline
- **AI-powered insights** by sending KPI data to a Groq LLM (LLaMA / Qwen) and returning plain-language actionable recommendations
- **Dynamic scheduling** for driver and bus schedule optimization
- **Forecasting** of KMs and operational hours using ML models

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Streamlit UI Layer                    │
│  login.py → app.py → [DM / RM / Admin dashboards]      │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│               FastAPI Backend (app.py)                  │
│  /ask_kpi endpoint → KPI compute → LLM insight          │
└────────┬──────────────────────────────┬─────────────────┘
         │                              │
┌────────▼────────┐          ┌──────────▼──────────┐
│   MySQL Database│          │   Groq LLM API       │
│  (depot data,   │          │  (LLaMA 3.3 70B /   │
│   users, KPIs)  │          │   Qwen3 32B fallback)│
└─────────────────┘          └─────────────────────┘
```

---

## 📁 Folder Structure

```
server/
│
├── dynamic_scheduling_master/       # Dynamic bus/driver scheduling module (subfolder)
│   └── ...                          # Scheduling algorithms and related scripts
│
├── __pycache__/                     # Python bytecode cache (auto-generated, ignore)
│
│── 🔧 CORE SERVER
├── app.py                           # Main FastAPI server — KPI endpoint, LLM integration
├── app_ui_admin.py                  # Streamlit UI shell for admin role
├── app_ui_dm.py                     # Streamlit UI shell for Depot Manager role
│
│── 🔐 AUTH & CONFIG
├── auth.py                          # Authentication logic — login, roles, DB user queries
├── login.py                         # Streamlit login page — session management
├── admin.py                         # Admin panel — user creation and management
├── config.json                      # Database credentials and app configuration
├── db_config.py                     # MySQL connection helper
├── models.py                        # SQLAlchemy ORM models for all DB tables (see Database Schema section)
│
│── 📊 DASHBOARD UIs
├── depot_UI.py                      # Combined depot dashboard entry point
├── depot_dashboard_dm.py            # Depot Manager's depot-level KPI dashboard
├── depot_dashboard_rm.py            # Regional Manager's depot-level KPI dashboard
├── driver_dashboard_DM.py           # Depot Manager's individual driver dashboard
├── driver_dashboard_RM.py           # Regional Manager's individual driver dashboard
├── driver_depot_dashboard_ui.py     # Shared driver + depot combined dashboard UI
├── depot_list.py                    # Fetches and displays list of depots for RM view
│
│── 📥 ETL PIPELINE
├── Etl_main.py                      # Streamlit ETL dashboard — upload, transform, load CSV to DB
├── upload_tables.py                 # Uploads processed tables into MySQL
├── insert.py                        # Raw insert utilities for DB population
├── edit_sheet.py                    # Sheet editing utilities for pre-processing data
├── operational_data.py              # Transform logic for operational data CSV uploads
├── pending.py                       # Handles pending/incomplete data entries
│
│── 🤖 AI / RAG PIPELINE
├── build_faiss_index.py             # Builds a FAISS vector index from depot documents
├── create_rag_documents.py          # Prepares and chunks documents for RAG indexing
├── retriever.py                     # FAISS-based semantic retriever for document search
├── faiss_index.bin                  # Pre-built FAISS binary index file
├── metadata.json                    # Document metadata store used by the API
│
│── 📈 KPI & RATIO CALCULATIONS
├── Ratios_DM.py                     # Computes KPI ratios for Depot Manager view
├── Ratios_RM.py                     # Computes KPI ratios for Regional Manager view
├── Ratios_tgsrtc.py                 # Computes organization-wide TSRTC KPI ratios
├── eight_ratios_DM.py               # Calculates the 8 core operational ratios (DM)
├── eight_ratios_RM.py               # Calculates the 8 core operational ratios (RM)
├── eight_ratios_tgsrtc.py           # Calculates the 8 core operational ratios (TSRTC-wide)
│
│── 🗓️ INPUT DATA MODULES
├── Input_Data_DM.py                 # Fetches and structures input data for DM dashboards
├── Input_Data_RM.py                 # Fetches and structures input data for RM dashboards
├── Input_Data_tgsrtc.py             # Fetches org-wide input data for TSRTC dashboards
│
│── 📋 ACTION PLANS
├── action_plan.py                   # Generates depot-level corrective action plans (DM)
├── action_plan_rm.py                # Generates corrective action plans for RM view
├── Action_plan_tgsrtc.py            # Generates TSRTC-wide action plans
│
│── 🔮 FORECASTING & ANALYTICS
├── forecast.py                      # XGBoost passenger forecast dashboard — predicts today's & tomorrow's passenger count per depot, stores results in MySQL, renders Plotly charts
├── kms_hrs.py                       # Computes KMs and operational hours from daily records
├── str_hrs.py                       # Calculates steerage/utilization hours per depot
├── train_kms_hrs.py                 # Trains XGBoost model on historical KM/hour data
├── backend_admin.py                 # Backend logic for admin-specific data operations
├── backend_dm.py                    # Backend logic for depot manager data operations
│
│── 🗃️ DATA FILES
├── SERVICEMASTER_HCU.csv            # Service master reference data for HCU depots
├── calender.csv                     # Calendar/holiday reference data
├── health.csv                       # Driver health/fitness tracking data
├── steering_hrs.csv                 # Steering hours reference data
│
│── 🖼️ ASSETS
├── LOGO.png                         # TSRTC application logo
├── driver_dashboard_logo.png        # Logo used in driver dashboard UI
│
│── 📦 ARCHIVES
├── dynamic_scheduling_master.zip    # Archived version of the scheduling module
├── dynamic_scheduling_master (2).zip # Second archived version (updated)
│
└── utils.py                         # Shared utility functions (DB engine, insert helpers)
```

---

---

## 🗄️ Database Schema

All tables are defined in `models.py` using SQLAlchemy ORM:

| Table | Description |
|---|---|
| `users` | User accounts with role, depot assignment, session tokens, and login lockout fields |
| `TS_ADMIN` | Depot master data — zone, region, depot name, category (RURAL/URBAN) |
| `input_data` | Core daily operational data per depot — schedules, KMs, driver availability, all KPI fields |
| `bus_details` | Bus-level records — bus number, type, engine make, KMs |
| `daily_operations` | Driver-level daily duty records — vehicle, service, route, earnings |
| `driver_absenteeism` | Driver leave and absence records by date and type |
| `driver_details` | Driver master data — name, age, DOB, joining date, gender |
| `ghc_2023` / `ghc_2024` | Driver health grading results for 2023 and 2024 |
| `action_plan` | Stores AI-generated action plan statuses per KPI per depot per date |
| `service_master` | Route/service master — service number, route, timings, KMs, day/night code |
| `predictive_planner_train` | Historical passenger data used for XGBoost model training |
| `predictive_planner_test` | Recent passenger data used for inference |
| `passenger_forecast_store` | Stores predicted and actual passenger counts per depot per date |

---

## ⚙️ Key Components Explained

### `app.py` — FastAPI AI Insight Server
The core backend. Exposes a single `/ask_kpi` POST endpoint that:
1. Fuzzy-matches the depot name from user input
2. Validates the requested KPI against 9 supported driver operation metrics
3. Fetches relevant records from `metadata.json` filtered by date range
4. Classifies the KPI average against Rural/Urban benchmarks (`CONTROL` / `WITHIN` / `RISK`)
5. Sends a structured prompt to the Groq LLM and returns actionable markdown recommendations

**Supported KPIs:**

| KPI Name | Benchmark (Rural) | Benchmark (Urban) |
|---|---|---|
| Weekly Off | 14% | 14% |
| Special Off | 25% | 27.4% |
| Others | 1.7% | 1% |
| Long Leave & Absent | 2% | 6% |
| Sick Leave | 2% | 2% |
| Spot Absent | 2% | 2% |
| Double Duty | 16% | 8% |
| Off Cancellation | 2% | 2% |
| Drivers/Schedule | 2.18 | 2.43 |

### `auth.py` — Authentication & Access Control
Handles MySQL-backed user authentication with role-based access. Supports roles: `admin`, `DM` (Depot Manager), `RM` (Regional Manager). Stores plain-text passwords in the `users` table (plain text — consider hashing for production).

### `Etl_main.py` — ETL Dashboard
A Streamlit-based data pipeline UI. Allows admins to upload CSV files, select a dataset type (Operational Data, Leave & Absent, Driver Details, Service Master), preview/transform the data, validate it, and load it into MySQL — all from the browser.

### `forecast.py` — Passenger Forecast Dashboard
A Streamlit page that uses a trained **XGBoost regressor** to predict today's and tomorrow's passenger count for the logged-in depot. It:
- Pulls historical data from `predictive_planner_train` and `predictive_planner_test` MySQL tables
- Engineers 20+ lag/rolling features (lag 1/7/30 days, 3/7-day rolling mean, EWM, pct change)
- Trains or loads a cached global model from disk (`/home/git/models/forecast/`)
- Blends model predictions with a 7-day recent mean for smoothing
- Persists predictions in `passenger_forecast_store` to avoid recalculation
- Renders interactive Plotly line charts (Actual vs Predicted) and variance bar charts

### `models.py` — Database ORM
Defines all 13 MySQL tables as SQLAlchemy models. The `InputData` table alone has 70+ columns covering every driver KPI, health reason, and schedule field. Used by the ETL pipeline and dashboards for consistent schema access.

---
An earlier retrieval approach using FAISS vector search over embedded depot documents. Still present in the codebase; the `/ask_kpi` endpoint now uses direct JSON/DB lookup instead.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + Uvicorn |
| Frontend UI | Streamlit |
| Database | MySQL (via `mysql-connector-python`) |
| LLM Provider | Groq API (LLaMA 3.3 70B, Qwen3 32B, LLaMA 3.1 8B) |
| Vector Search | FAISS (legacy RAG) |
| Fuzzy Matching | RapidFuzz |
| Forecasting | XGBoost + Scikit-learn |
| Visualization | Plotly |
| Data Processing | Pandas |

---

## 🔧 Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/GandamallaPradyumn/server.git
cd server
```

### 2. Install dependencies
```bash
pip install fastapi uvicorn streamlit mysql-connector-python groq rapidfuzz pandas faiss-cpu scikit-learn xgboost plotly sqlalchemy pymysql joblib
```

### 3. Configure the database
Edit `config.json` with your MySQL credentials:
```json
{
  "db": {
    "host": "localhost",
    "user": "root",
    "password": "*****",
    "database": "tsrtc_new"
  }
}
```

### 4. Set environment variables
```bash
export GROQ_API_KEY="your_groq_api_key_here"
```

### 5. Run the FastAPI server
```bash
python app.py
# or
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Run the Streamlit UI
```bash
streamlit run login.py
```

---

## 📡 API Usage

### `POST /ask_kpi`

Request body:
```json
{
  "depot": "Hyderabad Central",
  "kpi": "Spot Absent",
  "from_date": "2024-01-01",
  "to_date": "2024-01-31"
}
```

Response:
```json
{
  "depot": "HYDERABAD CENTRAL",
  "kpi": "Spot Absent",
  "average": 3.4,
  "benchmark": 2.0,
  "category": "URBAN",
  "summary": "#### Actionable Recommendations\n..."
}
```

---

## 👥 User Roles

| Role | Access |
|---|---|
| `admin` | ETL dashboard, user management, all depot data |
| `DM` | Depot Manager — single depot KPI view and driver dashboard |
| `RM` | Regional Manager — multi-depot overview and comparisons |

---

## 📌 Notes

- The `dynamic_scheduling_master/` subfolder contains the dynamic scheduling engine — refer to its internal documentation for usage.
- `metadata.json` acts as a flat-file data store for the AI endpoint. For production scale, replace with direct MySQL queries.
- The FAISS index (`faiss_index.bin`) is pre-built and used by the legacy retriever. Run `build_faiss_index.py` to rebuild if source documents change.
- Passwords are stored in plain text in the current implementation — hash them (e.g., bcrypt) before deploying to production.
