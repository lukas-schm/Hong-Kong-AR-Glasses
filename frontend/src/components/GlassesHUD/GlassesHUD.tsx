import { useEffect, useMemo, useRef, useState } from 'react';
import type { ExemplarPatient } from '../../data/exemplarPatients';
import './GlassesHUD.css';

/* ────────────────────────────────────────────────────────────────────────
   Even Realities G2 HUD mockup — lean monochrome green waveguide display.
   Left fixed: patient + top concerns. Bottom fixed: the plan.
   Right: swipeable cards (one per decision, then similar patients).
   ──────────────────────────────────────────────────────────────────────── */

interface GlassesHUDProps {
  patient: ExemplarPatient;
  onClose: () => void;
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
  { tx: 'Kept', survived: false, days: 'died day 12' },
];

function SimilarPatientsCard() {
  const survived = MOCK_SIMILAR.filter((r) => r.survived).length;
  return (
    <div className="ghud-card__body ghud-sentence">
      {survived} of the {MOCK_SIMILAR.length} most similar past patients survived.
    </div>
  );
}

export function GlassesHUD({ patient, onClose }: GlassesHUDProps) {
  const flags = useMemo(() => deriveRedFlags(patient), [patient]);
  const decisions = useMemo(() => deriveDecisions(patient), [patient]);
  const [card, setCard] = useState(0);
  const viewportRef = useRef<HTMLDivElement>(null);

  const cards = useMemo(() => {
    const list = [
      { title: 'Similar patients', render: () => <SimilarPatientsCard /> },
      ...decisions.map((d) => ({ title: d.axis, render: () => <DecisionCard decision={d} /> })),
    ];
    return list;
  }, [decisions]);
  const total = cards.length;

  const scrollToCard = (idx: number) => {
    const next = Math.max(0, Math.min(total - 1, idx));
    setCard(next);
    const vp = viewportRef.current;
    if (vp) vp.scrollTo({ top: next * vp.clientHeight, behavior: 'smooth' });
  };

  useEffect(() => {
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

  return (
    <div className="ghud-overlay" onClick={onClose}>
      <div className="ghud-display" onClick={(e) => e.stopPropagation()}>

        {/* ── Left fixed: patient + top concerns ── */}
        <aside className="ghud-left">
          <div className="ghud-name">{patient.name}</div>
          <div className="ghud-meta">{patient.subtitle}</div>
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
              <button key={c.title} className={`ghud-dot ${i === card ? 'ghud-dot--active' : ''}`} onClick={() => scrollToCard(i)} aria-label={c.title} />
            ))}
          </div>
        </main>

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
    </div>
  );
}
