import { useEffect, useMemo, type MouseEvent, type ReactNode } from 'react';
import type { ExemplarPatient } from '../../data/exemplarPatients';
import { useHudSync, setCard, setMenuIndex, selectPatient as syncSelect } from '../../utils/hudSync';
import './GlassesHUD.css';

/* ────────────────────────────────────────────────────────────────────────
   Even Realities G2 HUD — lean monochrome green waveguide display.

   Controlled & sync-aware: the active card and the patients-menu cursor live
   in the shared hudSync store, so the glasses and the monitor's embedded HUD
   stay mirror-synced. Navigated with the temple buttons (keyboard ◀▶▲▼⏎⎵).

   Cards: Patients worklist · Agent (agentic interaction) · one card per
   decision (antibiotics / fluids / BP) · Similar patients (territory-wide).
   Left fixed: patient + top concerns. Bottom fixed: the plan.
   ──────────────────────────────────────────────────────────────────────── */

export interface HUDAssistant {
  supported: boolean;
  listening: boolean;
  interim: string;
  lastUtterance: string | null;
  reply: string | null;
  busy: boolean;
  error?: 'mic-blocked' | 'no-mic' | 'no-speech' | 'network' | 'start-failed' | null;
  onTap: () => void;
}

export const VOICE_ERR: Record<string, { en: string; 'zh-HK': string }> = {
  'mic-blocked': { en: 'Mic blocked — allow it in the address bar, then tap again', 'zh-HK': '咪高峰被封鎖 — 喺網址列允許後再撳' },
  'no-mic': { en: 'No microphone found', 'zh-HK': '找不到咪高峰' },
  'no-speech': { en: 'No speech heard — tap and speak', 'zh-HK': '聽唔到聲 — 撳一下再講' },
  'network': { en: 'Speech network error — type below instead', 'zh-HK': '語音網絡錯誤 — 請改用打字' },
  'start-failed': { en: "Couldn't start the mic — tap again", 'zh-HK': '無法啟動咪高峰 — 再撳一下' },
};

export interface PatientMenuItem {
  referenceKey: string;
  name: string;
  subtitle: string;
  hospital: string;
  arm?: string;
}

export interface AgentStep {
  kind: 'voice' | 'intent' | 'tool' | 'model' | 'db-write' | 'reply' | 'info';
  text: string;
  ok?: boolean | null;
}

export interface CohortOutcomesLite {
  band: string;
  n: number;
  arms: Array<{ arm: string; n: number; survived: number; mortality: number }>;
}

interface GlassesHUDProps {
  /** null → standby: no patient loaded yet. */
  patient: ExemplarPatient | null;
  patients?: PatientMenuItem[];
  cohort?: CohortOutcomesLite | null;
  steps?: AgentStep[];
  onSelectPatient?: (referenceKey: string) => void;
  onClose: () => void;
  assistant?: HUDAssistant;
  lang?: 'en' | 'zh-HK';
  /** Show the control-hints strip (glasses + embedded). */
  controls?: boolean;
  /** Bind the temple buttons to the keyboard (glasses fullscreen only). */
  captureKeys?: boolean;
  /** Read-only mirror: bare display, no overlay, no input. */
  mirror?: boolean;
  /** Embedded interactive HUD: bare display, no overlay, taps still work. */
  embedded?: boolean;
}

const TXT = {
  patients: { en: 'Patients', 'zh-HK': '病人' },
  agent: { en: 'Agent', 'zh-HK': '智能助理' },
  similar: { en: 'Similar patients', 'zh-HK': '相似病人' },
  standby: { en: 'Standby', 'zh-HK': '待機' },
  noPatient: { en: 'no patient loaded', 'zh-HK': '未載入病人' },
  sayName: { en: 'Tap to talk, say a name — or pick below and tap.', 'zh-HK': '撳一撳講出姓名 — 或喺下面揀並撳一下。' },
  pickHint: { en: '▲▼ move · ⏎ open', 'zh-HK': '▲▼ 移動 · ⏎ 開啟' },
  thinking: { en: 'thinking…', 'zh-HK': '思考中…' },
  agentHint: { en: 'say a vital · an intervention · "de-escalate" · a name', 'zh-HK': '講出數據 · 介入 · 「降階」· 姓名' },
  controls: { en: '◀▶ cards · ▲▼ select · ⏎ tap · ⎵ talk', 'zh-HK': '◀▶ 卡片 · ▲▼ 揀 · ⏎ 撳 · ⎵ 講' },
  band: { high: { en: 'high severity', 'zh-HK': '高度嚴重' }, moderate: { en: 'moderate severity', 'zh-HK': '中度嚴重' }, low: { en: 'lower severity', 'zh-HK': '較輕' }, unknown: { en: 'similar', 'zh-HK': '相似' } },
} as const;

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

const ARM_NAME: Record<string, { en: string; 'zh-HK': string }> = {
  continue: { en: 'Continuing', 'zh-HK': '繼續廣譜' },
  deescalate: { en: 'Narrowing', 'zh-HK': '降階' },
  cease: { en: 'Stopping', 'zh-HK': '停藥' },
};

function SimilarCard({ cohort, lang }: { cohort?: CohortOutcomesLite | null; lang: 'en' | 'zh-HK' }) {
  if (!cohort || cohort.arms.length === 0) {
    return (
      <div className="ghud-card__body ghud-sentence ghud-sentence--similar">
        <div>{lang === 'zh-HK' ? '正在從 CDARS 擷取相似病人…' : 'Retrieving similar patients from CDARS…'}</div>
      </div>
    );
  }
  const best = cohort.arms[0];
  const worst = cohort.arms[cohort.arms.length - 1];
  const bandTxt = (TXT.band[(cohort.band as keyof typeof TXT.band)] ?? TXT.band.unknown)[lang];
  const bn = ARM_NAME[best.arm]?.[lang] ?? best.arm;
  const wn = ARM_NAME[worst.arm]?.[lang] ?? worst.arm;
  return (
    <div className="ghud-card__body ghud-sentence ghud-sentence--similar">
      {lang === 'zh-HK' ? (
        <div>
          {bandTxt}病人中，<strong>{bn}</strong> 死亡率最低
          （{best.survived}/{best.n} 存活），<strong>{wn}</strong> 最高（{worst.mortality}%）。
        </div>
      ) : (
        <div>
          In {bandTxt} patients, <strong>{bn}</strong> had the lowest mortality
          — <strong>{best.survived}/{best.n}</strong> survived — vs <strong>{wn}</strong> at {worst.mortality}%.
        </div>
      )}
      <div className="ghud-sentence__sub">
        {lang === 'zh-HK'
          ? `全港 CDARS · ${cohort.n} 名相似病人`
          : `territory-wide CDARS · ${cohort.n} similar patients`}
      </div>
    </div>
  );
}

const STEP_TAG: Record<AgentStep['kind'], string> = {
  voice: 'YOU', intent: 'INTENT', tool: 'CDARS', model: 'MODEL', 'db-write': 'WRITE', reply: 'LLM', info: 'INFO',
};

function AgentCard({ assistant, steps, lang }: { assistant?: HUDAssistant; steps?: AgentStep[]; lang: 'en' | 'zh-HK' }) {
  const recent = (steps ?? []).slice(-4);
  return (
    <div className="ghud-card__body ghud-agent">
      {recent.length > 0 && (
        <div className="ghud-agent__steps">
          {recent.map((s, i) => (
            <div key={i} className={`ghud-step ghud-step--${s.kind} ${s.ok === false ? 'ghud-step--bad' : ''}`}>
              <span className="ghud-step__tag">{STEP_TAG[s.kind]}</span>
              <span className="ghud-step__text">{s.text}</span>
            </div>
          ))}
        </div>
      )}
      <div className="ghud-agent__reply">
        {assistant?.busy ? (
          <span className="ghud-agent__thinking">{TXT.thinking[lang]}</span>
        ) : assistant?.reply ? (
          assistant.reply
        ) : (
          <span className="ghud-agent__hint">{TXT.agentHint[lang]}</span>
        )}
      </div>
    </div>
  );
}

function PatientsCard({
  patients, menuIndex, onSelect, lang,
}: { patients: PatientMenuItem[]; menuIndex: number; onSelect: (rk: string) => void; lang: 'en' | 'zh-HK' }) {
  if (patients.length === 0) {
    return <div className="ghud-card__body ghud-sentence">{TXT.sayName[lang]}</div>;
  }
  return (
    <div className="ghud-card__body ghud-menu">
      <ul className="ghud-menu__list">
        {patients.map((p, i) => (
          <li
            key={p.referenceKey}
            className={`ghud-menu__item ${i === menuIndex ? 'ghud-menu__item--active' : ''}`}
            onClick={(e) => { e.stopPropagation(); onSelect(p.referenceKey); }}
          >
            <span className="ghud-menu__cursor">{i === menuIndex ? '▸' : ''}</span>
            <span className="ghud-menu__name">{p.name}</span>
            <span className="ghud-menu__sub">{p.subtitle}</span>
          </li>
        ))}
      </ul>
      <div className="ghud-menu__hint">{TXT.pickHint[lang]}</div>
    </div>
  );
}

export function GlassesHUD({
  patient, patients = [], cohort, steps, onSelectPatient, onClose, assistant,
  lang = 'en', controls = false, captureKeys = false, mirror = false, embedded = false,
}: GlassesHUDProps) {
  const bare = mirror || embedded;
  const sync = useHudSync();
  const flags = useMemo(() => (patient ? deriveRedFlags(patient) : []), [patient]);
  const decisions = useMemo(() => (patient ? deriveDecisions(patient) : []), [patient]);

  const cards = useMemo(() => {
    const list: Array<{ id: string; title: string; render: () => ReactNode }> = [
      {
        id: 'patients', title: TXT.patients[lang],
        render: () => (
          <PatientsCard patients={patients} menuIndex={sync.menuIndex} lang={lang}
            onSelect={(rk) => { onSelectPatient?.(rk); syncSelect(rk); }} />
        ),
      },
      {
        id: 'agent', title: TXT.agent[lang],
        render: () => <AgentCard assistant={assistant} steps={steps} lang={lang} />,
      },
    ];
    if (patient) {
      decisions.forEach((d) => list.push({ id: d.id, title: d.axis, render: () => <DecisionCard decision={d} /> }));
      list.push({ id: 'similar', title: TXT.similar[lang], render: () => <SimilarCard cohort={cohort} lang={lang} /> });
    }
    return list;
  }, [patient, patients, cohort, steps, assistant, lang, sync.menuIndex, decisions, onSelectPatient]);

  const total = cards.length;
  const card = Math.max(0, Math.min(total - 1, sync.card));
  const onPatientsCard = cards[card]?.id === 'patients';

  // Land on the Agent card when a patient is freshly opened.
  useEffect(() => {
    if (patient) setCard(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient?.id]);

  const navCard = (delta: number) => setCard(Math.max(0, Math.min(total - 1, card + delta)));
  const moveCursor = (delta: number) => {
    if (onPatientsCard && patients.length) {
      setMenuIndex(Math.max(0, Math.min(patients.length - 1, sync.menuIndex + delta)));
    } else {
      navCard(delta);
    }
  };
  const activate = () => {
    if (onPatientsCard && patients[sync.menuIndex]) {
      onSelectPatient?.(patients[sync.menuIndex].referenceKey);
      syncSelect(patients[sync.menuIndex].referenceKey);
    } else {
      assistant?.onTap();
    }
  };

  useEffect(() => {
    if (!captureKeys) return;
    const onKey = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'Escape': onClose(); break;
        case 'ArrowLeft': e.preventDefault(); navCard(-1); break;
        case 'ArrowRight': e.preventDefault(); navCard(1); break;
        case 'ArrowUp': e.preventDefault(); moveCursor(-1); break;
        case 'ArrowDown': e.preventDefault(); moveCursor(1); break;
        case 'Enter': e.preventDefault(); activate(); break;
        case ' ': e.preventDefault(); assistant?.onTap(); break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // Tapping the waveguide toggles voice (temple-tap); click outside closes.
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
        <div className="ghud-name">{patient ? patient.name : ''}</div>
        <div className="ghud-meta">{patient ? patient.subtitle : TXT.noPatient[lang]}</div>
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

      {/* ── Right: one active card (button-navigated) ── */}
      <main className="ghud-right">
        <div className="ghud-tab">
          <span>{cards[card]?.title}</span>
          <span className="ghud-pager">{card + 1}/{total}</span>
        </div>
        <div className="ghud-cards ghud-cards--single">
          <section className="ghud-card">{cards[card]?.render()}</section>
        </div>
        <div className="ghud-dots">
          {cards.map((c, i) => (
            <button
              key={c.id}
              className={`ghud-dot ${i === card ? 'ghud-dot--active' : ''}`}
              onClick={(e) => { e.stopPropagation(); setCard(i); }}
              aria-label={c.title}
            />
          ))}
        </div>
      </main>

      {/* ── Assistant: tap-to-talk status + transcript ── */}
      {assistant && (
        <div className="ghud-assist">
          <span className={`ghud-assist__state ${assistant.listening ? 'ghud-assist__state--on' : ''}`}>
            {!assistant.supported ? '✕ NO VOICE' : assistant.listening ? '● LISTENING' : '○ TAP TO SPEAK'}
          </span>
          {assistant.interim ? (
            <span className="ghud-assist__interim">{assistant.interim}…</span>
          ) : assistant.error && !assistant.listening ? (
            <span className="ghud-assist__error">⚠ {VOICE_ERR[assistant.error]?.[lang] ?? assistant.error}</span>
          ) : assistant.lastUtterance ? (
            <span className="ghud-assist__chat">
              <span className="ghud-chat__row ghud-chat__row--user">
                <span className="ghud-chat__who">YOU</span>{assistant.lastUtterance}
              </span>
            </span>
          ) : (
            <span className="ghud-assist__hint">
              {controls ? TXT.controls[lang] : TXT.agentHint[lang]}
            </span>
          )}
        </div>
      )}

      {/* ── Bottom fixed: the plan / control hints ── */}
      <footer className="ghud-bottom">
        {patient ? (
          decisions.map((d) => {
            const recOpt = d.options.find((o) => o.key === d.recKey)!;
            return (
              <div key={d.id} className="ghud-plan">
                <span className="ghud-plan__axis">{d.axis}</span>
                <span className="ghud-plan__action">{recOpt.label}</span>
              </div>
            );
          })
        ) : (
          <div className="ghud-plan ghud-plan--hint">{controls ? TXT.controls[lang] : TXT.sayName[lang]}</div>
        )}
      </footer>
    </div>
  );

  if (bare) return display;
  return (
    <div className="ghud-overlay" onClick={onClose}>
      {display}
    </div>
  );
}
