# HONESTY.md

> Disclosed shortcuts are not penalized; hidden ones are. Truth here costs nothing.

## 1. Team
`git shortlog -sn`: Maxim (24), Lukas (6). Vishisht — no commits (videos + product).

| Member | Handle | Did |
|---|---|---|
| Lukas Schmidt | `lukas-schm` | Causal model & pipeline, paper, FastAPI backend + inference, React app |
| Maxim Akishin | `MaximA21` | G2 glasses plugin, phone mirror/remote, Gemini voice |
| Vishisht Choudhary | — | Product & storytelling lead; advised throughout; directed/recorded/edited both videos |

## 2. Fully working (real logic)
- **Recommendations** come from a causal-ML model trained on **real de-identified ICU data** (MIMIC-IV, n=9,331 sepsis-3). That model lives in the full repo; this branch serves its **cached** per-arm outputs.
- **CDARS API + WebSocket bus** (`api/`) — real warehouse / query / audit endpoints + glasses↔web sync (data synthetic, §3).
- **React app** — `#monitor` / `#cdars` / `#glasses`.
- **G2 glasses plugin** — runs on hardware: navigation, phone mirror, remote controls.
- **Voice Q&A** (`/agent/ask`) — Gemini transcribes + reasons in one call, Google-Search-grounded with the patient's CDARS record.

## 3. Mocked / hardcoded
*Synthetic data is a **deliberate** privacy choice (real records can't go on an AR demo — PhysioNet DUA), not unbuilt logic.*

| What | Where | Real version |
|---|---|---|
| Demo patient records are synthetic by design; "Hong Kong EHR" is a UI scaffold (`HKEHR/`), not a dataset | `api/cdars/seed.py` | Real CDARS / HK EHR warehouse feed |
| Per-arm numbers **and** recommendation are cached/hardcoded — no live model in this AR build (it's trained upstream) | `seed.py`, `service.py:predict_arms` | Score each patient through the live model |
| "Agent" is a rule-based planner unless `ANTHROPIC_API_KEY` set | `api/agent/planner.py`, `router.py` | LLM tool-use (wired in `llm.py`) |
| Glasses backend = hardcoded LAN IP | `glasses-plugin/app.json` | Configurable endpoint |

## 4. External services
| Service | For | Real? | Auth |
|---|---|---|---|
| Google Gemini (`gemini-3.5-flash`) | Voice transcription + reasoning | Real | `GEMINI_API_KEY` |
| Google Search grounding | Citations | Real | (Gemini key) |
| Anthropic Claude | Optional agent engine | Real when keyed, else planner | `ANTHROPIC_API_KEY` (optional) |
| MIMIC-IV | Training the upstream model (not in this branch) | Real dataset, offline | PhysioNet DUA (gitignored) |

## 5. Pre-existing code
The causal model, pipeline, and manuscript are prior team research ("CHAI antibiotic", first committed **2026-05-28**) and are **not** on this branch. The glasses plugin, voice integration, and CDARS warehouse were built during the hackathon (**2026-06-06→07**).

| Item | Source | License |
|---|---|---|
| Causal model + pipeline + paper (upstream, not in this branch) | Team's prior "CHAI antibiotic" research | team-owned |
| Even Hub SDK + plugin scaffold | `@evenrealities/even_hub_sdk` template | vendor |
| Libraries | FastAPI, React, google-genai | OSS |

## 6. Limitations & what's next
- **Live predictions.** Right now the glasses show pre-computed risk numbers. Next step: run each patient through the real model live, so the figures update per patient.
- **Stronger evidence.** The underlying study is suggestive, not proof — it points to a hypothesis a proper clinical trial would still need to confirm.
- **Production hardening.** No logins or user accounts yet, and the glasses connect to a fixed network address that has to be set by hand.
