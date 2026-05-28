import { useState, useEffect, useRef } from 'react';
import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import { fetchPrediction } from '../../api';
import type { ExtendedOutcomes } from '../../types';
import './TrajectoryChart.css';

const ARMS = [
  { id: 'continue',   label: 'Continue',    color: '#e85c4a', colorDim: 'rgba(232,92,74,0.35)' },
  { id: 'deescalate', label: 'De-escalate', color: '#2e8bff', colorDim: 'rgba(46,139,255,0.35)' },
  { id: 'cease',      label: 'Cease',       color: '#37d6a0', colorDim: 'rgba(55,214,160,0.35)' },
] as const;

function trajectoryPoints(p28: number, nPts = 80): { t: number; y: number }[] {
  // Constant-hazard model: F(t) = 1 - (1-p28/100)^(t/28)
  const frac = p28 / 100;
  return Array.from({ length: nPts + 1 }, (_, i) => {
    const t = (i / nPts) * 28;
    const y = (1 - Math.pow(1 - frac, t / 28)) * 100;
    return { t, y };
  });
}

type ArmId = 'continue' | 'deescalate' | 'cease';

export function TrajectoryChart() {
  const state = usePatientState();
  const dispatch = usePatientDispatch();
  const [predictions, setPredictions] = useState<Partial<Record<ArmId, ExtendedOutcomes>>>({});
  const [loading, setLoading] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  // Re-fetch all 3 arms whenever a new prediction completes for the active arm
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);

    Promise.all(
      ARMS.map(arm =>
        fetchPrediction(state, arm.id, ac.signal)
          .then(r => ({ id: arm.id as ArmId, r }))
          .catch(() => null),
      ),
    ).then(results => {
      if (ac.signal.aborted) return;
      const next: Partial<Record<ArmId, ExtendedOutcomes>> = {};
      for (const result of results) {
        if (result) next[result.id] = result.r;
      }
      setPredictions(next);
      setLoading(false);
      // Sync the active arm's outcomes back to global state
      const active = next[state.activeTreatmentId as ArmId];
      if (active) dispatch({ type: 'SET_API_OUTCOMES', outcomes: active });
    });

    return () => ac.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    // Re-fetch when any model-relevant patient param changes
    state.sofa, state.sapsii, state.lactate, state.vaso, state.ventilation, state.aki,
    state.crp, state.wbc, state.temperature, state.cultureResult, state.antibioticDays,
    state.age, state.female, state.comorbidity, state.immunocompromised,
    state.map, state.activeTreatmentId,
  ]);

  // Chart geometry
  const W = 320, H = 190;
  const PAD = { top: 14, right: 44, bottom: 34, left: 34 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;

  const allP28 = ARMS.map(a => predictions[a.id]?.withTreatment ?? 0);
  const yMax = Math.max(40, Math.ceil(Math.max(...allP28) / 10) * 10 + 10);

  const toX = (t: number) => (t / 28) * cW;
  const toY = (y: number) => cH - (y / yMax) * cH;

  const yGridLines = [0, 10, 20, 30, 40, 50, 60].filter(v => v <= yMax);

  return (
    <div className="traj-chart">
      <div className="traj-chart__header">
        <span className="traj-chart__title">28-Day Mortality Trajectory</span>
        {loading && <span className="traj-chart__loading">Calculating…</span>}
      </div>

      {/* Treatment selector legend */}
      <div className="traj-chart__legend">
        {ARMS.map(arm => {
          const isActive = arm.id === state.activeTreatmentId;
          const p28 = predictions[arm.id]?.withTreatment;
          return (
            <button
              key={arm.id}
              className={`traj-chart__arm-btn${isActive ? ' traj-chart__arm-btn--active' : ''}`}
              style={{ '--arm-color': arm.color } as React.CSSProperties}
              onClick={() => dispatch({ type: 'SET_ACTIVE_TREATMENT', treatmentId: arm.id })}
            >
              <span className="traj-chart__arm-dot" style={{ background: isActive ? arm.color : arm.colorDim }} />
              <span className="traj-chart__arm-label">{arm.label}</span>
              {p28 !== undefined && !loading && (
                <span className="traj-chart__arm-val" style={{ color: isActive ? arm.color : 'var(--text-dim)' }}>
                  {p28.toFixed(1)}%
                </span>
              )}
            </button>
          );
        })}
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="traj-chart__svg"
        style={{ opacity: loading ? 0.35 : 1, transition: 'opacity 0.3s ease' }}
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid + Y labels */}
          {yGridLines.map(v => (
            <g key={v}>
              <line
                x1={0} y1={toY(v)} x2={cW} y2={toY(v)}
                stroke="#2a3a52" strokeWidth={v === 0 ? 0.8 : 0.5}
                strokeDasharray={v === 0 ? '' : '3,4'}
              />
              <text
                x={-5} y={toY(v)}
                textAnchor="end" dominantBaseline="middle"
                fill="#8fa4c5" fontSize={7.5}
                fontFamily="JetBrains Mono, monospace"
              >
                {v}%
              </text>
            </g>
          ))}

          {/* X grid + labels */}
          {[0, 7, 14, 21, 28].map(d => (
            <g key={d}>
              <line x1={toX(d)} y1={0} x2={toX(d)} y2={cH}
                stroke="#2a3a52" strokeWidth={0.5} />
              <text
                x={toX(d)} y={cH + 12}
                textAnchor="middle" fill="#8fa4c5" fontSize={7.5}
                fontFamily="JetBrains Mono, monospace"
              >
                {d === 0 ? 'D0' : d === 28 ? 'D28' : `D${d}`}
              </text>
            </g>
          ))}

          {/* Axis label */}
          <text
            x={cW / 2} y={cH + 26}
            textAnchor="middle" fill="#8fa4c5" fontSize={7}
            fontFamily="JetBrains Mono, monospace"
          >
            Days from decision
          </text>

          {/* Trajectory lines — dimmed first, active on top */}
          {[...ARMS].reverse().map(arm => {
            const p28 = predictions[arm.id]?.withTreatment;
            if (p28 === undefined) return null;
            const pts = trajectoryPoints(p28);
            const d = pts
              .map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.t).toFixed(1)},${toY(p.y).toFixed(1)}`)
              .join(' ');
            const isActive = arm.id === state.activeTreatmentId;
            return (
              <path
                key={arm.id}
                d={d}
                fill="none"
                stroke={arm.color}
                strokeWidth={isActive ? 2.5 : 1.5}
                opacity={isActive ? 1 : 0.45}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}

          {/* Day-28 endpoint labels */}
          {(() => {
            // Sort by p28 descending to stagger labels
            const sorted = [...ARMS]
              .map(arm => ({ arm, p28: predictions[arm.id]?.withTreatment }))
              .filter(x => x.p28 !== undefined)
              .sort((a, b) => b.p28! - a.p28!);
            return sorted.map(({ arm, p28 }, rank) => {
              const base = toY(p28!);
              const offset = rank === 0 ? -1 : rank === 1 ? 7 : 15;
              const isActive = arm.id === state.activeTreatmentId;
              return (
                <text
                  key={arm.id}
                  x={cW + 4}
                  y={base + offset}
                  fill={arm.color}
                  fontSize={7.5}
                  dominantBaseline="middle"
                  fontFamily="JetBrains Mono, monospace"
                  fontWeight={isActive ? '700' : '400'}
                  opacity={isActive ? 1 : 0.6}
                >
                  {p28!.toFixed(1)}%
                </text>
              );
            });
          })()}
        </g>
      </svg>

      {/* Causal effect summary for active treatment */}
      {(() => {
        const o = predictions[state.activeTreatmentId as ArmId];
        if (!o || loading) return null;
        const arm = ARMS.find(a => a.id === state.activeTreatmentId)!;
        const ate = o.ate;
        const benefit = ate < 0;
        return (
          <div className="traj-chart__ate">
            <span className="traj-chart__ate-label">
              Causal effect (<span style={{ color: arm.color }}>{arm.label}</span>):
            </span>
            <span className={`traj-chart__ate-val ${benefit ? 'traj-chart__ate-val--benefit' : 'traj-chart__ate-val--harm'}`}>
              {benefit ? '' : '+'}{ate.toFixed(1)} pp
            </span>
            <span className="traj-chart__ate-ci">
              [{o.ateLowerBound.toFixed(1)}, {o.ateUpperBound.toFixed(1)}]
            </span>
            <span className={`traj-chart__confidence traj-chart__confidence--${o.confidence}`}>
              {o.confidence}
            </span>
          </div>
        );
      })()}

      {/* OOD warning */}
      {(() => {
        const o = predictions[state.activeTreatmentId as ArmId];
        if (!o?.ood?.outOfDistribution) return null;
        return (
          <div className="traj-chart__ood-warn">
            ! Patient profile unusual vs. training cohort — estimate is an extrapolation
          </div>
        );
      })()}
    </div>
  );
}
