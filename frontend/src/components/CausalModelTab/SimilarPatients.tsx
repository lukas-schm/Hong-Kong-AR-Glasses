import { useState } from 'react';
import type { SimilarPatient } from '../../types';
import './SimilarPatients.css';

interface SimilarPatientsProps {
  patients: SimilarPatient[];
  selectedPatients: SimilarPatient[];
  onTogglePatient: (p: SimilarPatient) => void;
}

export function SimilarPatients({ patients, selectedPatients, onTogglePatient }: SimilarPatientsProps) {
  const [expanded, setExpanded] = useState(false);
  const selectedIds = new Set(selectedPatients.map(p => p.id));

  return (
    <div className="sim-patients">
      <button className="sim-patients__header" onClick={() => setExpanded(v => !v)}>
        <span className="sim-patients__title">Similar Patients ({patients.length})</span>
        <span className="sim-patients__chevron">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="sim-patients__table-wrap">
          <table className="sim-patients__table">
            <thead>
              <tr>
                <th>Age</th>
                <th>SOFA</th>
                <th>CRP</th>
                <th>Culture</th>
                <th>ABx Days</th>
                <th>Treatment</th>
                <th>Outcome</th>
                <th>Sim</th>
              </tr>
            </thead>
            <tbody>
              {patients.map(p => {
                const isSelected = selectedIds.has(p.id);
                return (
                  <tr
                    key={p.id}
                    className={`sim-patients__row ${isSelected ? 'sim-patients__row--selected' : ''}`}
                    onClick={() => onTogglePatient(p)}
                  >
                    <td>{p.age}</td>
                    <td>{p.sofa}</td>
                    <td>{p.crp.toFixed(1)}</td>
                    <td>
                      <span className={`sim-patients__culture sim-patients__culture--${p.cultureResult}`}>
                        {p.cultureResult}
                      </span>
                    </td>
                    <td>{p.antibioticDays}d</td>
                    <td>
                      <span className={`sim-patients__tx sim-patients__tx--${p.treatment}`}>
                        {p.treatment === 'continue' ? 'Cont.' : p.treatment === 'deescalate' ? 'De-esc.' : 'Ceased'}
                      </span>
                    </td>
                    <td>
                      <span className={`sim-patients__outcome sim-patients__outcome--${p.outcome.toLowerCase()}`}>
                        {p.outcome}
                      </span>
                    </td>
                    <td>
                      <div className="sim-patients__sim-bar">
                        <div
                          className="sim-patients__sim-fill"
                          style={{ width: `${Math.round(p.sim * 100)}%` }}
                        />
                        <span>{Math.round(p.sim * 100)}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
