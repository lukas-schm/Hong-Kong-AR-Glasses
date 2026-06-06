import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import type { ExemplarPatient } from '../../data/exemplarPatients';
import './GlassesHUD.css';

/* ────────────────────────────────────────────────────────────────────────
   Even Realities G2 HUD mockup — lean monochrome green waveguide display.
   Left fixed: patient + top concerns. Bottom fixed: the plan.
   Right: swipeable cards (one per decision, then similar patients).
   ──────────────────────────────────────────────────────────────────────── */

export interface HUDAssistant {
  supported: boolean;
  listening: boolean;
  /** Live partial transcript while the user is speaking. */
  interim: string;
  /** Last final voice transcript — shown as the user's side of the chat. */
  lastUtterance: string | null;
  /** Last assistant reply, rendered inside the waveguide. */
  reply: string | null;
  busy: boolean;
  /** Tap on the glasses (anywhere on the display) toggles listening. */
  onTap: () => void;
}

interface GlassesHUDProps {
  /** null → standby: no patient loaded yet, tap and say a name. */
  patient: ExemplarPatient | null;
  onClose: () => void;
  assistant?: HUDAssistant;
  /** Read-only mirror: bare display, no overlay, no input. */
  mirror?: boolean;
  /** Embedded interactive HUD: bare display, no overlay, taps still work. */
  embedded?: boolean;
}

interface RedFlag { label: string; value: string; severity: 'crit' | 'warn' }

function deriveRedFlags(p: ExemplarPatient): RedFlag[] {
  const pr = p.profile;
  const flags: RedFlag[] = [];
  if ((pr.map ?? 99) < 65) flags.push({ label: 'Low blood pressure', value: `${pr.map}`, severity: 'crit' });
  if ((pr.lactate ?? 0) >= 4) flags.push({ label: 'High lactate', value: `${pr.lactate}`, severity: 'crit' });
  else if ((pr.lactate ?? 0) >= 2) flags.push({ label: 'Raised lactate', value: `${pr.lactate}`, severity: 'warn' });
  if ((pr.sofa ?? 0) >= 9) flags.push({ label: 'Critically ill', value: `${pr.sofa}/24`, severity: 'crit' });
  else if ((pr.sofa ?? 0) >= 6) flags.push({ label: 'Seriously ill', value: `${pr.sofa}/24`, severity: 'warn' });
  if (pr.vaso === 'YES') flags.push({ label: 'On BP meds', value: '', severity: 'crit' });
  if (pr.ventilation === 'YES') flags.push({ label: 'On ventilator', value: '', severity: 'warn' });
  if ((pr.spo2 ?? 100) < 92) flags.push({ label: 'Low oxygen', value: `${pr.spo2}%`, severity: 'warn' });
  if ((pr.aki ?? 0) >= 2) flags.push({ label: 'Kidneys struggling', value: '', severity: 'warn' });
  if (pr.cultureResult === 'pending') flags.push({ label: 'Cultures pending', value: '', severity: 'warn' });
  return flags.slice(0, 3);
}

interface DecisionOption { key: string; label: string; dash?: string; mortality: number }
interface Decision { id: 'abx' | 'fluids' | 'pressors'; axis: string; options: DecisionOption[]; recKey: string }

const DASH = [undefined, '5 4', '2 4'];

function deriveDecisions(p: ExemplarPatient): Decision[] {
  const pr = p.profile;
  const o = p.outcomes;
  const base = o[o.recommendedAction];

  const abx: Decision = {
    id: 'abx', axis: 'Antibiotics', recKey: o.recommendedAction,
    options: [
      { key: 'continue', label: 'Keep', dash: DASH[0], mortality: o.continue },
      { key: 'deescalate', label: 'Narrow', dash: DASH[1], mortality: o.deescalate },
      { key: 'cease', label: 'Stop', dash: DASH[2], mortality: o.cease },
    ],
  };

  const hypoperfused = (pr.map ?? 99) < 65 || (pr.lactate ?? 0) >= 4;
  const overloaded = (pr.aki ?? 0) >= 2 || (pr.urineOutput ?? 9999) < 600;
  const fluidsRec = hypoperfused ? 'bolus' : overloaded ? 'restrict' : 'maintain';
  const fluids: Decision = {
    id: 'fluids', axis: 'Fluids', recKey: fluidsRec,
    options: [
      { key: 'bolus', label: 'More', dash: DASH[0], mortality: base + (hypoperfused ? -4 : 5) },
      { key: 'maintain', label: 'Steady', dash: DASH[1], mortality: base + (hypoperfused ? 2 : overloaded ? 1 : -2) },
      { key: 'restrict', label: 'Less', dash: DASH[2], mortality: base + (overloaded ? -3 : hypoperfused ? 7 : 1) },
    ],
  };

  const onVaso = pr.vaso === 'YES';
  const hypotensive = (pr.map ?? 99) < 65;
  const pressorsRec = onVaso && hypotensive ? 'escalate' : onVaso ? 'wean' : 'none';
  const pressors: Decision = {
    id: 'pressors', axis: 'BP support', recKey: pressorsRec,
    options: [
      { key: 'escalate', label: 'More', dash: DASH[0], mortality: base + (hypotensive ? -5 : 4) },
      { key: 'wean', label: 'Less', dash: DASH[1], mortality: base + (onVaso && !hypotensive ? -2 : 6) },
      { key: 'none', label: 'None', dash: DASH[2], mortality: base + (onVaso ? 9 : -1) },
    ],
  };

  return [abx, fluids, pressors];
}

function trajectory(endRisk: number, startRisk: number): number[] {
  return Array.from({ length: 15 }, (_, d) => {
    const t = d / 14;
    const eased = 1 - Math.pow(1 - t, 2.2);
    return startRisk + (endRisk - startRisk) * eased + Math.sin(d * 1.7 + endRisk) * (1 - t);
  });
}

/* Lean decision card: one headline + a clean sparkline, no axes or boxes. */
function DecisionCard({ decision }: { decision: Decision }) {
  const W = 300;
  const H = 96;
  const recOpt = decision.options.find((o) => o.key === decision.recKey)!;
  const start = Math.max(...decision.options.map((o) => o.mortality)) * 0.9 + 6;
  const series = decision.options.map((o) => ({ ...o, points: trajectory(o.mortality, start) }));
  const all = series.flatMap((s) => s.points);
  const lo = Math.min(...all) - 2;
  const hi = Math.max(...all) + 2;
  const x = (d: number) => (d / 14) * (W - 36);
  const y = (v: number) => H - 6 - ((v - lo) / (hi - lo)) * (H - 18);
  const nextBest = Math.min(...decision.options.filter((o) => o.key !== decision.recKey).map((o) => o.mortality));
  const delta = Math.round(nextBest - recOpt.mortality);

  return (
    <div className="ghud-card__body ghud-dcard">
      <div className="ghud-head">
        <span className="ghud-head__action">{recOpt.label}</span>
        <span className="ghud-head__mort">{Math.round(recOpt.mortality)}% risk</span>
      </div>
      {delta > 0 && <div className="ghud-sub">{delta}% better than next best</div>}
      <svg viewBox={`0 0 ${W} ${H}`} className="ghud-svg">
        {series.filter((s) => s.key !== decision.recKey).map((s) => (
          <g key={s.key}>
            <polyline points={s.points.map((v, d) => `${x(d)},${y(v)}`).join(' ')} className="ghud-line ghud-line--alt" strokeDasharray={s.dash} />
            <text x={x(14) + 4} y={y(s.points[14]) + 3} className="ghud-svg-label--alt">{Math.round(s.mortality)}</text>
          </g>
        ))}
        {series.filter((s) => s.key === decision.recKey).map((s) => (
          <g key={s.key}>
            <polyline points={s.points.map((v, d) => `${x(d)},${y(v)}`).join(' ')} className="ghud-line ghud-line--rec" />
            <text x={x(14) + 4} y={y(s.points[14]) + 3} className="ghud-svg-label">{Math.round(s.mortality)}</text>
          </g>
        ))}
      </svg>
      <div className="ghud-axis-row"><span>now</span><span>2 weeks</span></div>
    </div>
  );
}

const MOCK_SIMILAR = [
  { tx: 'Narrowed', survived: true, days: 'home day 9' },
  { tx: 'Narrowed', survived: true, days: 'home day 11' },
  { tx: 'Kept', survived: true, days: 'home day 14' },
  { tx: 'Stopped', survived: false, days: 'died day 6' },
  { tx: 'Stopped', survived: false, days: 'died day 12' },
];

const TX_PHRASE: Record<string, string> = {
  Narrowed: 'narrowing antibiotics',
  Kept: 'keeping broad cover',
  Stopped: 'stopping antibiotics',
};

function SimilarPatientsCard() {
  // Contrast outcomes by treatment so the takeaway is what was done and
  // what happened, not just a head count.
  const groups = Array.from(
    MOCK_SIMILAR.reduce((m, r) => {
      const g = m.get(r.tx) ?? { tx: r.tx, n: 0, survived: 0 };
      g.n += 1;
      if (r.survived) g.survived += 1;
      return m.set(r.tx, g);
    }, new Map<string, { tx: string; n: number; survived: number }>()).values(),
  ).sort((a, b) => b.survived / b.n - a.survived / a.n);
  const best = groups[0];
  const worst = groups[groups.length - 1];
  const bestPhrase = TX_PHRASE[best.tx] ?? best.tx.toLowerCase();
  return (
    <div className="ghud-card__body ghud-sentence ghud-sentence--similar">
      <div>
        {bestPhrase.charAt(0).toUpperCase() + bestPhrase.slice(1)} led to survival
        — <strong>{best.survived} of {best.n}</strong> went home — while{' '}
        {TX_PHRASE[worst.tx] ?? worst.tx.toLowerCase()} generally led to death
        — <strong>{worst.n - worst.survived} of {worst.n}</strong> died.
      </div>
      <div className="ghud-sentence__sub">
        from the {MOCK_SIMILAR.length} most similar past patients
      </div>
    </div>
  );
}

export function GlassesHUD({ patient, onClose, assistant, mirror = false, embedded = false }: GlassesHUDProps) {
  const bare = mirror || embedded; // bare = no fullscreen overlay
  const flags = useMemo(() => (patient ? deriveRedFlags(patient) : []), [patient]);
  const decisions = useMemo(() => (patient ? deriveDecisions(patient) : []), [patient]);
  const [card, setCard] = useState(0);
  const viewportRef = useRef<HTMLDivElement>(null);

  const cards = useMemo(() => {
    if (!patient) {
      return [{
        title: 'Standby',
        render: () => (
          <div className="ghud-card__body ghud-sentence">
            Tap, then say a patient name — e.g. “Chan Tai Man”.
          </div>
        ),
      }];
    }
    return [
      { title: 'Similar patients', render: () => <SimilarPatientsCard /> },
      ...decisions.map((d) => ({ title: d.axis, render: () => <DecisionCard decision={d} /> })),
    ];
  }, [patient, decisions]);
  const total = cards.length;

  const scrollToCard = (idx: number) => {
    const next = Math.max(0, Math.min(total - 1, idx));
    setCard(next);
    const vp = viewportRef.current;
    if (vp) vp.scrollTo({ top: next * vp.clientHeight, behavior: 'smooth' });
  };

  useEffect(() => {
    if (bare) return; // an embedded/mirror HUD must not capture page keys
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') scrollToCard(card + 1);
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') scrollToCard(card - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const handleScroll = () => {
    const vp = viewportRef.current;
    if (!vp) return;
    const idx = Math.round(vp.scrollTop / vp.clientHeight);
    if (idx !== card) setCard(idx);
  };

  // Tapping anywhere on the glasses display toggles voice listening
  // (temple-tap metaphor); clicking outside the display closes the HUD.
  const handleDisplayTap = (e: MouseEvent) => {
    e.stopPropagation();
    if (!mirror) assistant?.onTap();
  };

  const display = (
    <div
      className={`ghud-display ${assistant?.listening ? 'ghud-display--listening' : ''} ${bare ? 'ghud-display--bare' : ''} ${mirror ? 'ghud-display--mirror' : ''}`}
      onClick={handleDisplayTap}
    >

        {/* ── Left fixed: patient + top concerns ── */}
        <aside className="ghud-left">
          <div className="ghud-name">{patient ? patient.name : 'CDSS'}</div>
          <div className="ghud-meta">{patient ? patient.subtitle : 'no patient loaded'}</div>
          <ul className="ghud-flags">
            {flags.map((f) => (
              <li key={f.label} className={`ghud-flag ghud-flag--${f.severity}`}>
                <span>{f.severity === 'crit' ? '▲' : '△'}</span>
                <span>{f.label}</span>
                {f.value && <span className="ghud-flag__val">{f.value}</span>}
              </li>
            ))}
          </ul>
        </aside>

        {/* ── Right: swipeable cards ── */}
        <main className="ghud-right">
          <div className="ghud-tab">
            <span>{cards[card].title}</span>
            <span className="ghud-pager">{card + 1}/{total}</span>
          </div>
          <div className="ghud-cards" ref={viewportRef} onScroll={handleScroll}>
            {cards.map((c) => (
              <section className="ghud-card" key={c.title}>{c.render()}</section>
            ))}
          </div>
          <div className="ghud-dots">
            {cards.map((c, i) => (
              <button
                key={c.title}
                className={`ghud-dot ${i === card ? 'ghud-dot--active' : ''}`}
                onClick={(e) => { e.stopPropagation(); scrollToCard(i); }}
                aria-label={c.title}
              />
            ))}
          </div>
        </main>

        {/* ── Assistant: tap-to-talk status + transcript + reply ── */}
        {assistant && (
          <div className="ghud-assist">
            <span className={`ghud-assist__state ${assistant.listening ? 'ghud-assist__state--on' : ''}`}>
              {!assistant.supported ? '✕ NO VOICE' : assistant.listening ? '● LISTENING' : '○ TAP TO SPEAK'}
            </span>
            {assistant.interim ? (
              <span className="ghud-assist__interim">{assistant.interim}…</span>
            ) : assistant.busy || assistant.reply ? (
              <span className="ghud-assist__chat">
                {assistant.lastUtterance && (
                  <span className="ghud-chat__row ghud-chat__row--user">
                    <span className="ghud-chat__who">YOU</span>
                    {assistant.lastUtterance}
                  </span>
                )}
                <span className="ghud-chat__row ghud-chat__row--llm">
                  <span className="ghud-chat__who">LLM</span>
                  {assistant.busy ? <i>thinking…</i> : assistant.reply}
                </span>
              </span>
            ) : (
              <span className="ghud-assist__hint">
                {patient ? 'say a vital · an intervention · another name' : 'say a patient name'}
              </span>
            )}
          </div>
        )}

        {/* ── Bottom fixed: the plan ── */}
        <footer className="ghud-bottom">
          {decisions.map((d) => {
            const recOpt = d.options.find((o) => o.key === d.recKey)!;
            return (
              <div key={d.id} className="ghud-plan">
                <span className="ghud-plan__axis">{d.axis}</span>
                <span className="ghud-plan__action">{recOpt.label}</span>
              </div>
            );
          })}
        </footer>
    </div>
  );

  // Bare modes render just the display (the monitor frame scales it);
  // the standalone mode keeps the click-outside-to-close overlay.
  if (bare) return display;
  return (
    <div className="ghud-overlay" onClick={onClose}>
      {display}
    </div>
  );
}
