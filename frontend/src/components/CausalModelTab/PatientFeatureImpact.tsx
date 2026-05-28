import { useState } from 'react';
import type { ExtendedOutcomes } from '../../types';
import './PatientFeatureImpact.css';

interface PatientFeatureImpactProps {
  outcomes: ExtendedOutcomes;
  treatmentId: string;
}

export function PatientFeatureImpact({ outcomes }: PatientFeatureImpactProps) {
  const [open, setOpen] = useState(false);
  const pfi = outcomes.patientFeatureImportance;

  if (!pfi || pfi.contributions.length === 0) return null;

  const top = [...pfi.contributions]
    .sort((a, b) => b.importance - a.importance)
    .slice(0, 6);

  const maxAbs = Math.max(...top.map(c => Math.abs(c.contribution)), 0.01);

  return (
    <div className="pfi">
      <button className="pfi__header" onClick={() => setOpen(v => !v)}>
        <span className="pfi__title">Per-Patient Feature Importance</span>
        <span className="pfi__chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="pfi__content">
          <div className="pfi__legend">
            <span className="pfi__legend-dot pfi__legend-dot--increase" />
            <span>Increases mortality</span>
            <span className="pfi__legend-dot pfi__legend-dot--decrease" />
            <span>Decreases mortality</span>
          </div>
          {top.map(c => {
            const barWidth = Math.abs(c.contribution) / maxAbs * 100;
            return (
              <div key={c.feature} className="pfi__row">
                <div className="pfi__row-label">
                  <span className="pfi__feature">{c.label}</span>
                  <span className="pfi__value">
                    {typeof c.patientValue === 'boolean'
                      ? (c.patientValue ? 'Yes' : 'No')
                      : String(c.patientValue)}
                  </span>
                </div>
                <div className="pfi__bar-wrap">
                  <div
                    className={`pfi__bar pfi__bar--${c.direction}`}
                    style={{ width: `${barWidth}%` }}
                  />
                  <span className="pfi__contrib">
                    {c.contribution > 0 ? '+' : ''}{c.contribution.toFixed(2)} pp
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
