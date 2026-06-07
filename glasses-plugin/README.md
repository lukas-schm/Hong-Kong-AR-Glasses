# CDARS CDSS · Even G2 plugin

Runs the CDARS voice-first CDSS on Even Realities G2 smart glasses as an
[Even Hub](https://hub.evenrealities.com/docs) plugin. The plugin is a web
app loaded into the Even App's WebView on the phone; the glasses render
container pages (576×288, 16-shade green) pushed over BLE — they run no code.

It joins the existing realtime bus as `role=glasses`, so patient selection,
card navigation and agent activity stay **mirror-synced** with `#monitor`
and `#cdars` on the desktop, exactly like the browser `#glasses` view.

## Layout

```
WORKLIST                              PATIENT
┌ CDARS · ACTIVE PATIENTS (4) ● ┐    ┌ CHAN Tai Man 67M · ICU ────────┐
│ > CHAN Tai Man · QEH · keep   │    │ !! High lactate │ ANTIBIOTICS  │
│   WONG Siu Ming · PWH · …     │    │ !! Low BP       │ > Keep   32% │
│   …                           │    │ !  On vent      │   Narrow 38% │
├ scroll: move · tap: open ─────┤    ├ ● LISTENING… / YOU/LLM chat ───┤
└───────────────────────────────┘    └────────────────────────────────┘
```

Temple touchpad: worklist — scroll moves the cursor, tap opens the patient.
Patient page — scroll cycles the 4 cards (Antibiotics / Fluids / BP support /
Similar patients), tap toggles the mic, double-tap returns to the worklist.

## Run it

```bash
# 1. backend reachable from the phone (run_demo.sh now binds 0.0.0.0:8002)
./scripts/run_demo.sh

# 2. serve the plugin on the LAN
cd glasses-plugin
npm install
npm run dev          # vite on 0.0.0.0:5173

# 3. sideload
npm run qr           # QR with ?server=http://<lan-ip>:8002 baked in
```

Scan the QR from the Even App (Even Hub → sideload). Phone and Mac must be
on the same Wi-Fi (or a Tailscale net — set the server URL in the phone
panel, which the plugin's WebView page shows on the phone screen).

### If the Even App shows no QR scanner

The scan/sideload entry is gated on a **developer account**: register at
[hub.evenrealities.com](https://hub.evenrealities.com) with the same email
you use in the Even App, run `evenhub login`, and update the Even App to the
latest version (Even Hub features shipped April 2026, app ≥ 2.0).

No-scanner fallback — upload a private build to the dev portal instead:

```bash
npm run build
evenhub pack app.json dist -o cdars-cdss.ehpk   # CLI: npm i -g @evenrealities/evenhub-cli
```

then upload `cdars-cdss.ehpk` at hub.evenrealities.com (private/test build)
and install it from the Hub on your own glasses. A packed build has no
`?server=` param — set the CDARS server URL once in the phone panel.
Note `app.json`'s network whitelist pins the server IP; re-pack if your
LAN IP changes.

## Files

| file | role |
| --- | --- |
| `src/main.ts` | entry: bridge + bus + gestures + agent wiring |
| `src/render.ts` | state → G2 container pages (rebuild / flicker-free upgrade) |
| `src/bus.ts` | port of `frontend/src/utils/bus.ts` (absolute WS URL) |
| `src/cdars.ts` | trimmed port of `frontend/src/api/cdars.ts` |
| `src/clinical.ts` | red flags + decision derivation from `GlassesHUD.tsx` |
| `src/voice.ts` | G2 mic (16 kHz PCM) → WAV → server ASR |
| `src/phonePanel.ts` | phone-screen ops panel (server URL, status, log) |
| `src/config.ts` | server base resolution (`?server=` → localStorage → env) |

## Server-side ASR

The G2 has no on-device/WebView speech recognition — the SDK streams raw
16 kHz mono 16-bit PCM (`audioControl(true)` → `audioEvent`). `src/voice.ts`
buffers it and POSTs a WAV to:

```
POST /api/v1/agent/voice?lang=en|zh-HK   (Content-Type: audio/wav)
→ { "text": "…", "language": "en", "engine": "faster-whisper" }
```

Served by `api/agent/asr.py` (faster-whisper, lazy-loaded singleton).
`CDARS_ASR_MODEL` picks the checkpoint (default `base`; use `large-v3` for
proper Cantonese — `zh-HK` tries whisper's `yue` and falls back to `zh`).
The plugin then feeds the transcript through `/api/v1/agent/command`.

## Notes / G2 constraints

- Max 12 containers/page (8 text), one `isEventCapture: 1`; list ≤ 20 items
  × 64 chars; text ≤ 1000 chars at startup / 2000 on upgrade.
- `createStartUpPageContainer` once, `rebuildPageContainer` thereafter;
  bridge UI calls are serialized in `Renderer.enqueue` (the glasses choke
  on concurrent transmissions).
- Chinese display: the worklist/cards currently render `nameEn`; the G2
  built-in font does render CJK — switch to `nameZh` in `render.ts` if wanted.
