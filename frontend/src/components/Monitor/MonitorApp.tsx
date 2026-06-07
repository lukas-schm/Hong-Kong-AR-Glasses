import { useEffect, useMemo, useRef, useState } from 'react';
import { GlassesHUD, VOICE_ERR } from '../GlassesHUD/GlassesHUD';
import { useLang, LangToggle } from '../../i18n';
import { useCdssSession } from '../../hooks/useCdssSession';
import { bus, type BusActivity, type BusEvent } from '../../utils/bus';
import { getHudState, setCard, setMenuIndex, useHudSync } from '../../utils/hudSync';
import { subscribeMonitor, type MonitorEvent } from '../../utils/monitor';
import './Monitor.css';

/* ────────────────────────────────────────────────────────────────────────
   #monitor — the model monitor. Hosts the live G2 HUD (mirror-synced with
   the glasses over the bus) and a plain-language console of everything the
   system is doing: voice → CDARS retrieval → causal model → write-back, in
   easy language, with the raw technical stream tucked behind a toggle.

   The treatment recommendation / risk numbers live on the HUD (and the
   glasses); the monitor stays a pure activity console.
   ──────────────────────────────────────────────────────────────────────── */

interface LogRow { seq: number; kind: BusActivity['kind'] | 'model-req' | 'model-res'; text: string; detail?: string; source?: string }

const KIND_TAG: Record<string, string> = {
  voice: 'VOICE', intent: 'INTENT', tool: 'CDARS', model: 'MODEL', 'db-write': 'DB WRITE',
  reply: 'REPLY', info: 'INFO', 'model-req': 'MODEL →', 'model-res': 'MODEL ←',
};

export function MonitorApp() {
  const { lang, t } = useLang();
  const s = useCdssSession('monitor');
  const sync = useHudSync();
  const { exemplar } = s;
  const [draft, setDraft] = useState('');
  const submitDraft = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    void s.sendText(text);
  };

  /* ── full activity log (server) + local technical model events ── */
  const [log, setLog] = useState<LogRow[]>([]);
  useEffect(() => {
    const off = bus.subscribe((ev: BusEvent) => {
      if (ev.type !== 'activity') return;
      const a = ev as BusActivity;
      const text = lang === 'zh-HK' && a.textZh ? a.textZh : a.text;
      setLog((prev) => [...prev.slice(-299), { seq: a.seq, kind: a.kind, text, detail: a.detail, source: a.source }]);
    });
    return off;
  }, [lang]);
  // Client-side model calls (legacy /predict) surface in the technical log too.
  useEffect(() => subscribeMonitor((ev: MonitorEvent) => {
    if (ev.kind === 'model-req') {
      setLog((prev) => [...prev.slice(-299), { seq: 1_000_000 + ev.seq, kind: 'model-req', text: `arm=${ev.arm}`, detail: 'client /predict' }]);
    } else if (ev.kind === 'model-res') {
      setLog((prev) => [...prev.slice(-299), { seq: 1_000_000 + ev.seq, kind: 'model-res', text: `arm=${ev.arm} → ${ev.mortality}%` }]);
    }
  }), []);

  const techRef = useRef<HTMLDivElement>(null);
  useEffect(() => { techRef.current?.scrollTo({ top: techRef.current.scrollHeight }); }, [log]);

  /* ── plain-language feed (you / step / chart / model) ── */
  interface FeedItem { id: number; who: 'you' | 'model' | 'chart' | 'step'; text: string }
  const feed: FeedItem[] = useMemo(() => {
    const items: FeedItem[] = [];
    for (const r of log) {
      if (r.kind === 'voice') items.push({ id: r.seq, who: 'you', text: r.text });
      else if (r.kind === 'reply') items.push({ id: r.seq, who: 'model', text: r.text });
      else if (r.kind === 'db-write') items.push({ id: r.seq, who: 'chart', text: r.text });
      else if (r.kind === 'tool' || r.kind === 'model') items.push({ id: r.seq, who: 'step', text: r.text });
    }
    return items.slice(-14);
  }, [log]);
  const feedRef = useRef<HTMLDivElement>(null);
  useEffect(() => { feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' }); }, [feed]);

  /* ── HUD navigation controls (drive the synced store) ── */
  const total = s.current ? 6 : 2;
  const onPatients = sync.card === 0;
  const nav = (d: number) => setCard(Math.max(0, Math.min(total - 1, getHudState().card + d)));
  const cursor = (d: number) => {
    if (onPatients && s.menuItems.length) setMenuIndex(Math.max(0, Math.min(s.menuItems.length - 1, getHudState().menuIndex + d)));
    else nav(d);
  };
  const activate = () => {
    if (onPatients && s.menuItems[sync.menuIndex]) s.selectPatient(s.menuItems[sync.menuIndex].referenceKey);
    else s.assistant.onTap();
  };

  const others = s.presence.filter((r) => r !== 'monitor');

  return (
    <div className="mon">
      <header className="mon-header">
        <span className="mon-logo">Emily</span>
        <span className={`mon-conn ${s.connected ? 'on' : ''}`}>
          {s.connected ? `◉ live${others.length ? ` · ${others.join(' · ')}` : ''}` : '○ offline'}
        </span>
        <a className="mon-jump" href="#cdars">CDARS ↗</a>
        <LangToggle />
        <span className={`mon-pulse ${s.assistant.listening ? 'on' : ''}`}>
          {s.assistant.listening ? `● ${t('listening')}` : '○'}
        </span>
      </header>

      {/* ── Live glasses (interactive mirror), on top ── */}
      <section className="mon-hud-top">
        <div className="mon-hud-frame">
          <div className="mon-hud-scale">
            <GlassesHUD
              patient={exemplar}
              patients={s.menuItems}
              cohort={s.cohort}
              steps={s.steps}
              onSelectPatient={s.selectPatient}
              onClose={() => {}}
              assistant={s.assistant}
              lang={lang}
              controls
              embedded
            />
          </div>
        </div>

        {/* on-screen temple buttons — mirror the glasses' physical controls */}
        <div className="mon-controls" role="group" aria-label="HUD controls">
          <button onClick={() => nav(-1)} title="Previous card">◀</button>
          <button onClick={() => cursor(-1)} title={onPatients ? 'Up' : 'Previous'}>▲</button>
          <button onClick={() => cursor(1)} title={onPatients ? 'Down' : 'Next'}>▼</button>
          <button onClick={() => nav(1)} title="Next card">▶</button>
          <button onClick={activate} title="Tap / open">⏎</button>
          <button className={s.assistant.listening ? 'on' : ''} onClick={() => s.assistant.onTap()} title="Talk">🎤</button>
        </div>

        {/* Typed-command fallback — always works, even without a mic. */}
        <form className="mon-say" onSubmit={submitDraft}>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={lang === 'zh-HK'
              ? '打字輸入指令，例如「開啟陳大文」、「乳酸記低 3.2」、「降階」'
              : 'Type a command — e.g. "show Chan Tai Man", "set lactate to 3.2", "de-escalate"'}
          />
          <button type="submit">{t('send')}</button>
        </form>
        {s.assistant.error && !s.assistant.listening && (
          <div className="mon-voicewarn">
            ⚠ {VOICE_ERR[s.assistant.error]?.[lang] ?? s.assistant.error}
          </div>
        )}

        <div className="mon-patient">
          {s.current ? (
            <>
              <strong>{s.current.nameEn} {s.current.nameZh}</strong>
              <span className="mon-mono">{s.current.hkid} · {s.current.hospitalCode}{s.current.referenceKey ? ` · CDARS ${s.current.referenceKey}` : ''}</span>
              <span className="mon-dim">{lang === 'zh-HK' ? s.current.subtitle.zh : s.current.subtitle.en}</span>
            </>
          ) : (
            <span className="mon-dim">{t('monStart')}</span>
          )}
          {!s.assistant.supported && <span className="mon-warn">Voice needs Chrome/Edge + mic permission — controls above still work.</span>}
        </div>
      </section>

      {/* ── Activity + model log (no recommendation panel) ── */}
      <main className="mon-main">
        {s.current && (
          <>
            <section className="mon-feed">
              <h2>{t('monActivity')}</h2>
              <div className="mon-feed__list" ref={feedRef}>
                {feed.length === 0 && <div className="mon-dim">—</div>}
                {feed.map((it) => (
                  <div key={it.id} className={`mon-bubble mon-bubble--${it.who}`}>
                    <span className="mon-bubble__who">
                      {it.who === 'you' ? t('monYou') : it.who === 'chart' ? '📝' : it.who === 'step' ? '⚙' : t('monAssistant')}
                    </span>
                    <span className="mon-bubble__text">{it.text}</span>
                  </div>
                ))}
                {s.assistant.busy && <div className="mon-bubble mon-bubble--model"><span className="mon-bubble__who">{t('monAssistant')}</span><span className="mon-bubble__text"><i>{t('monWaiting')}</i></span></div>}
              </div>
            </section>
          </>
        )}

        <details className="mon-tech">
          <summary>{t('monTechLog')} <span className="mon-tech__count">{log.length}</span></summary>
          <div className="mon-log" ref={techRef}>
            {log.map((r) => (
              <div key={r.seq} className={`mon-row mon-row--${r.kind}`}>
                <span className="mon-seq">{String(r.seq % 1000).padStart(3, '0')}</span>
                <span className="mon-kind">{KIND_TAG[r.kind] ?? r.kind}</span>
                <span className="mon-summary">{r.text}{r.detail ? `  ·  ${r.detail}` : ''}</span>
              </div>
            ))}
          </div>
        </details>
      </main>
    </div>
  );
}
