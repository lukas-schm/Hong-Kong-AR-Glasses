<div align="center">

# 🧫 CDARS CDSS — AR build

### Voice-first antibiotic-stewardship decision support on smart glasses

A clinical decision-support system that puts antibiotic-stewardship guidance where the
decision happens — on a clinician's face. A web dashboard, a Hong Kong **CDARS**-style
data warehouse, and a voice-first **Even Realities G2** smart-glasses HUD.

> **This branch is the AR/CDARS application.** The causal-ML model that produces the
> recommendations is trained separately (on real de-identified ICU data) and lives in
> the full research repo; here, per-arm risk is served from cached warehouse values.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-web-61DAFB?logo=react&logoColor=black)
![Gemini](https://img.shields.io/badge/Gemini-voice-4285F4?logo=google&logoColor=white)
![Even G2](https://img.shields.io/badge/Even%20Realities-G2-111111)

</div>

---

## Architecture

```
          ┌──────────────── Even Realities G2 ────────────────┐
          │  voice-first HUD · tap-to-talk · phone mirror+remote │
          └──────────────────────┬─────────────────────────────┘
                                 │  BLE · Even Hub SDK
                        glasses-plugin/  (TypeScript · Vite)
                                 │
   ┌──────────────┐  REST + WebSocket bus  ┌──────┴───────────────────────────┐
   │  frontend/   │◀──────────────────────▶│              api/                  │
   │  React web   │  #monitor #cdars #glasses│  FastAPI · CDARS warehouse (SQLite)│
   └──────────────┘                         │  Gemini voice · realtime bus       │
                                            └──────┬───────────────────────────┘
                                                   │  cached per-arm risk
                                   ┌───────────────┴────────────────┐
                                   │  causal model — trained upstream │  (real MIMIC-IV;
                                   │  on real data, not in this build │   full repo)
                                   └─────────────────────────────────┘
```

## 🚀 Quickstart

### Backend + web dashboard

```bash
pip install -r requirements.txt
./run_demo.sh                  # API → :8002   ·   web → :5000
```

Then open (in Chrome/Edge, via `localhost`):

| View | URL | What it is |
|---|---|---|
| **Monitor** | `localhost:5000/#monitor` | Live model monitor + HUD mirror; narrates each agent step |
| **CDARS** | `localhost:5000/#cdars` | Cohort workbench, patient dashboard, audit trail |
| **Glasses** | `localhost:5000/#glasses` | The G2 surface in the browser — voice + on-screen controls |

> Optional keys: `export GEMINI_API_KEY=…` enables tap-to-talk voice Q&A (Gemini + Google
> Search grounding); `export ANTHROPIC_API_KEY=…` enables the Claude agent. Without them,
> a deterministic planner drives the agent — no key needed.

### Glasses plugin (Even Realities G2)

```bash
cd glasses-plugin && npm install
npm run dev          # serve the plugin on :5173
npm run simulate     # desktop G2 simulator
npm run qr           # QR to sideload onto the glasses via the Even app
npm run build && npm run pack   # → cdars-cdss.ehpk (upload to the Even Hub dev portal)
```

The plugin renders to the glasses **and** mirrors to the phone with on-screen controls
(scroll · tap · back). Tap-to-talk asks Gemini about the open patient, grounded in their
CDARS record.

---

## 🗂️ Layout

| Path | What it is |
|---|---|
| **`api/`** | FastAPI backend — CDARS warehouse (SQLite), REST, realtime bus, agent, Gemini voice |
| **`frontend/`** | React web app — `#monitor` · `#cdars` · `#glasses` |
| **`glasses-plugin/`** | Even Hub **G2 plugin** — voice-first CDSS + phone mirror & remote control |
| `run_demo.sh` | Launches API + web together |

## 🔌 API surface

Base path `/api/v1`:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `WS` | `/ws?role=…` | Realtime bus — relays `hud`/`nav`/`select`, broadcasts `activity` |
| `GET` | `/cdars/active` · `/cdars/patient/{id}` · `/…/cohort` | Warehouse reads (cached per-arm risk) |
| `GET` | `/cdars/stats` · `/cdars/audit` · `POST /cdars/query` · `/cdars/feed` | Warehouse query + audit trail |
| `POST` | `/agent/ask` | Voice Q&A — WAV + patient context → Gemini (transcribe + reason + ground) |
| `POST` | `/agent/command` · `GET /agent/engine` | Agentic actions on the warehouse |

---

## 🔒 Data & ethics

- **Patient data here is synthetic** — the CDARS warehouse is seeded by `api/cdars/seed.py`.
  Real records can't be shown on an AR demo (privacy + the PhysioNet DUA).
- Per-arm risk shown for demo patients is **cached** (the live model is not part of this
  build — it's trained upstream on real MIMIC-IV data).
- Decision-support / hypothesis-generating only. Research prototype, **not** a medical device.

See [`HONESTY.md`](HONESTY.md) for the full disclosure of what's real vs. mocked.
