import { useEffect, useMemo, useRef, useState } from 'react';
import { subscribeMonitor, monitor, type MonitorEvent } from '../../utils/monitor';
import { GlassesHUD } from '../GlassesHUD/GlassesHUD';
import { useLang } from '../../i18n';
import { useVoice } from '../../utils/voice';
import { runAssistant, type AssistantAction } from '../../utils/assistant';
import { predictAllArms, bestArm, type Arm, type ArmPredictions } from '../../utils/prediction';
import { hkToExemplar } from '../../utils/hkAdapter';
import type { HKPatient } from '../../data/hkPatients';
import './Monitor.css';

/* ────────────────────────────────────────────────────────────────────────
   The whole app: a clinician-friendly model monitor. Left: the live,
   interactive G2 HUD (tap to talk). Right: a plain-language view of what
   the model recommends and what just happened — with the raw technical
   log tucked behind a toggle for the data team.
   ──────────────────────────────────────────────────────────────────────── */

const ARM_ORDER: Arm[] = ['continue', 'deescalate', 'cease'];

// hud events drive the mirror and never appear in the log.
type LogEvent = Exclude<MonitorEvent, { kind: 'hud' }>;

const KIND_TAG: Record<LogEvent['kind'], string> = {
  input: 'VOICE', intent: 'INTENT', patient: 'PATIENT',
  'model-req': 'MODEL →', 'model-res': 'MODEL ←', 'db-write': 'DB WRITE', reply: 'REPLY',
};
const FEATURE_KEYS = ['sofa', 'lactate', 'map', 'crp', 'wbc', 'spo2', 'vaso', 'ventilation', 'age'] as const;

function techSummary(ev: LogEvent): string {
  switch (ev.kind) {
    case 'input': return `“${ev.text}”  (${ev.source}, ${ev.lang})`;
    case 'intent': return `${ev.intent}${ev.detail ? `  ·  ${ev.detail}` : ''}`;
    case 'patient': return `${ev.name}  ·  ${ev.hkid}`;
    case 'model-req': {
      const f = ev.features as Record<string, unknown>;
      return `arm=${ev.arm}  {${FEATURE_KEYS.filter((k) => f[k] !== undefined).map((k) => `${k}=${f[k]}`).join(', ')}}`;
    }
    case 'model-res': return `arm=${ev.arm}  →  ${ev.mortality}% mortality`;
    case 'db-write': return `${ev.label}:  ${ev.from} → ${ev.to}`;
    case 'reply': return ev.text.split('\n')[0];
  }
}

interface FeedItem { id: number; who: 'you' | 'model' | 'chart'; text: string }

export function MonitorApp() {
  const { lang, t } = useLang();

  /* ── Patient + live predictions ── */
  const [patient, setPatient] = useState<HKPatient | null>(null);
  const [preds, setPreds] = useState<ArmPredictions | null>(null);

  useEffect(() => {
    if (!patient) { setPreds(null); return; }
    const ctrl = new AbortController();
    setPreds(null);
    predictAllArms(patient, ctrl.signal)
      .then((p) => { if (!ctrl.signal.aborted) setPreds(p); })
      .catch(() => {});
    return () => ctrl.abort();
  }, [patient]);

  /* ── Voice assistant ── */
  const [assistReply, setAssistReply] = useState<string | null>(null);
  const [assistUtterance, setAssistUtterance] = useState<string | null>(null);
  const [assistBusy, setAssistBusy] = useState(false);
  const ctxRef = useRef({ patient, preds });
  ctxRef.current = { patient, preds };

  const handleAction = (action: AssistantAction) => {
    if (action.type === 'open-patient') setPatient(action.patient);
    else if (action.type === 'show-all') setPatient(null);
    else if (action.type === 'write-record') {
      const cur = ctxRef.current.patient;
      action.writes.forEach((w) =>
        monitor({ kind: 'db-write', field: String(w.key), label: w.label, from: String(cur?.profile[w.key] ?? '—'), to: String(w.value) }),
      );
      setPatient((prev) => {
        if (!prev) return prev;
        const profile = { ...prev.profile } as Record<string, unknown>;
        action.writes.forEach((w) => { profile[w.key] = w.value; });
        return { ...prev, profile: profile as typeof prev.profile };
      });
    }
  };

  const handleUtterance = async (text: string) => {
    setAssistUtterance(text);
    setAssistReply(null);
    setAssistBusy(true);
    try {
      const { patient: p, preds: bp } = ctxRef.current;
      const reply = await runAssistant(text, { patient: p, basePredictions: bp, source: 'voice' });
      setAssistReply(reply.text);
      if (reply.action) handleAction(reply.action);
    } finally {
      setAssistBusy(false);
    }
  };

  const voice = useVoice(lang, handleUtterance);
  useEffect(() => { setAssistReply(null); setAssistUtterance(null); }, [patient?.hkid]);

  const hudPatient = useMemo(
    () => (patient ? hkToExemplar(patient, lang, preds ?? undefined) : null),
    [patient, lang, preds],
  );

  /* ── Recommendation + risk-change detection ── */
  const best: Arm | null = preds ? bestArm(preds.values) : null;
  const worst: Arm | null = preds
    ? ARM_ORDER.reduce((a, b) => (preds.values[a] >= preds.values[b] ? a : b))
    : null;
  const prevRef = useRef<{ hkid: string; val: number } | null>(null);
  const [change, setChange] = useState<{ from: number; to: number } | null>(null);
  useEffect(() => {
    if (!preds || !patient || !best) { prevRef.current = null; setChange(null); return; }
    const val = preds.values[best];
    const prev = prevRef.current;
    if (prev && prev.hkid === patient.hkid && prev.val !== val) setChange({ from: prev.val, to: val });
    else if (!prev || prev.hkid !== patient.hkid) setChange(null);
    prevRef.current = { hkid: patient.hkid, val };
  }, [preds, patient, best]);

  const armLabel: Record<Arm, string> = {
    continue: t('armContinue'), deescalate: t('armDeescalate'), cease: t('armCease'),
  };

  /* ── Event log → plain-language feed + raw technical log ── */
  const [events, setEvents] = useState<LogEvent[]>([]);
  const techRef = useRef<HTMLDivElement>(null);
  useEffect(() => subscribeMonitor((ev) => {
    if (ev.kind === 'hud') return;
    setEvents((prev) => [...prev.slice(-249), ev]);
  }), []);
  useEffect(() => { techRef.current?.scrollTo({ top: techRef.current.scrollHeight }); }, [events]);

  const feed: FeedItem[] = useMemo(() => {
    const items: FeedItem[] = [];
    for (const ev of events) {
      if (ev.kind === 'input') items.push({ id: ev.seq, who: 'you', text: ev.text });
      else if (ev.kind === 'db-write') items.push({ id: ev.seq, who: 'chart', text: `${t('monCharted')} — ${ev.label}: ${ev.from} → ${ev.to}` });
      else if (ev.kind === 'reply') items.push({ id: ev.seq, who: 'model', text: ev.text });
    }
    return items.slice(-12);
  }, [events, t]);
  const feedRef = useRef<HTMLDivElement>(null);
  useEffect(() => { feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' }); }, [feed]);

  return (
    <div className="mon">
      <header className="mon-header">
        <span className="mon-logo">CDARS CDSS</span>
        <span className={`mon-pulse ${voice.listening ? 'on' : ''}`}>{voice.listening ? `● ${t('listening')}` : '○'}</span>
      </header>

      {/* ── Live glasses (interactive), on top ── */}
      <section className="mon-hud-top">
        <div className="mon-hud-frame">
          <div className="mon-hud-scale">
            <GlassesHUD
              embedded
              patient={hudPatient}
              onClose={() => {}}
              assistant={{
                supported: voice.supported, listening: voice.listening, interim: voice.interim,
                lastUtterance: assistUtterance, reply: assistReply, busy: assistBusy, onTap: voice.toggle,
              }}
            />
          </div>
        </div>
        <div className="mon-patient">
          {patient ? (
            <>
              <strong>{patient.nameEn} {patient.nameZh}</strong>
              <span className="mon-mono">{patient.hkid} · {patient.hospitalCode}</span>
              <span className="mon-dim">{lang === 'zh-HK' ? patient.subtitle.zh : patient.subtitle.en}</span>
            </>
          ) : (
            <span className="mon-dim">—</span>
          )}
          {!voice.supported && <span className="mon-warn">Voice needs Chrome/Edge + mic permission.</span>}
        </div>
      </section>

      {/* ── Recommendation + activity + model log, below ── */}
      <main className="mon-main">
          {!patient ? null : (
            <>
              <section className="mon-reco">
                <div className="mon-reco__head">
                  <h2>{t('monRecommends')}</h2>
                  {change && (
                    <span className={`mon-change ${change.to < change.from ? 'down' : 'up'}`}>
                      {t('monChanged')}: {change.from}% → {change.to}% {t('monAfterUpdate')}
                    </span>
                  )}
                </div>

                {!preds ? (
                  <div className="mon-dim mon-waiting">{t('monWaiting')}</div>
                ) : (
                  <>
                    <p className="mon-reco__lead">
                      {t('monExplain')} <strong>{armLabel[best!]}</strong> — <strong>{preds.values[best!]}%</strong> {t('monRiskOfDeath')}.
                    </p>
                    <div className="mon-bars">
                      {ARM_ORDER.map((a) => {
                        const v = preds.values[a];
                        const tone = a === best ? 'best' : a === worst ? 'worst' : 'mid';
                        return (
                          <div key={a} className={`mon-bar mon-bar--${tone}`}>
                            <span className="mon-bar__label">
                              {armLabel[a]}
                              {a === best && <span className="mon-bar__badge">{t('monLowest')}</span>}
                            </span>
                            <span className="mon-bar__track">
                              <span className="mon-bar__fill" style={{ width: `${v}%` }} />
                            </span>
                            <span className="mon-bar__val">{v}%</span>
                          </div>
                        );
                      })}
                    </div>
                    <p className="mon-reco__foot">{t('monRiskOfDeath')} · {lang === 'zh-HK' ? patient.outcomes.recommendation.zh : patient.outcomes.recommendation.en}</p>
                  </>
                )}
              </section>

              <section className="mon-feed">
                <h2>{t('monActivity')}</h2>
                <div className="mon-feed__list" ref={feedRef}>
                  {feed.length === 0 && <div className="mon-dim">—</div>}
                  {feed.map((it) => (
                    <div key={it.id} className={`mon-bubble mon-bubble--${it.who}`}>
                      <span className="mon-bubble__who">
                        {it.who === 'you' ? t('monYou') : it.who === 'chart' ? '📝' : t('monAssistant')}
                      </span>
                      <span className="mon-bubble__text">{it.text}</span>
                    </div>
                  ))}
                  {assistBusy && <div className="mon-bubble mon-bubble--model"><span className="mon-bubble__who">{t('monAssistant')}</span><span className="mon-bubble__text"><i>{t('monWaiting')}</i></span></div>}
                </div>
              </section>
            </>
          )}

          {/* Raw model I/O for the data team */}
          <details className="mon-tech">
            <summary>{t('monTechLog')} <span className="mon-tech__count">{events.length}</span></summary>
            <div className="mon-log" ref={techRef}>
              {events.map((ev) => (
                <div key={ev.seq} className={`mon-row mon-row--${ev.kind}`}>
                  <span className="mon-seq">{String(ev.seq).padStart(3, '0')}</span>
                  <span className="mon-kind">{KIND_TAG[ev.kind]}</span>
                  <span className="mon-summary">{techSummary(ev)}</span>
                </div>
              ))}
            </div>
          </details>
        </main>
    </div>
  );
}
