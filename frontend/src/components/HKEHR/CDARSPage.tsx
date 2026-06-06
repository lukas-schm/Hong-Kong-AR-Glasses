import { useMemo, useState } from 'react';
import {
  ICD9_CATALOG, emptyCriteria, queryCdars,
  type CDARSCriteria, type CDARSEpisode, type EpisodeType,
} from '../../data/cdars';
import { haHospitals, hkPatients, type HKPatient } from '../../data/hkPatients';
import { useLang, LangToggle } from '../../i18n';
import './HKEHR.css';

/* ────────────────────────────────────────────────────────────────────────
   Mocked CDARS — Clinical Data Analysis and Reporting System.
   Real-world workflow mirrored: define criteria → de-identified
   line-listing keyed by Reference Key (never the HKID) + aggregate
   counts. ICD-9-CM diagnoses, BNF drug sections, local lab test names,
   Death Registry linkage.
   ──────────────────────────────────────────────────────────────────────── */

interface CDARSPageProps {
  onBack: () => void;
  /** Demo-only bridge: re-identify a current admission into eHRSS. */
  onOpenPatient: (patient: HKPatient) => void;
}

const EPISODE_TYPES: Array<{ value: EpisodeType; label: string }> = [
  { value: 'IP', label: 'Inpatient' },
  { value: 'SOPC', label: 'SOPC (Specialist Outpatient)' },
  { value: 'GOPC', label: 'GOPC (General Outpatient)' },
  { value: 'AE', label: 'A&E (Emergency)' },
];

const CLUSTERS = [...new Set(haHospitals.map((h) => h.clusterCode))];

export function CDARSPage({ onBack, onOpenPatient }: CDARSPageProps) {
  const { t } = useLang();
  const [criteria, setCriteria] = useState<CDARSCriteria>({ ...emptyCriteria, dxCode: '995.92' });
  const [extracted, setExtracted] = useState<CDARSEpisode[] | null>(null);

  const set = <K extends keyof CDARSCriteria>(key: K, value: CDARSCriteria[K]) =>
    setCriteria((c) => ({ ...c, [key]: value }));

  const counts = useMemo(() => {
    if (!extracted) return null;
    return {
      episodes: extracted.length,
      patients: new Set(extracted.map((e) => e.referenceKey)).size,
      deaths: extracted.filter((e) => e.death).length,
    };
  }, [extracted]);

  const handleExtract = () => setExtracted(queryCdars(criteria));

  const handleReidentify = (e: CDARSEpisode) => {
    const patient = hkPatients.find((p) => p.hkid === e.linkedHkid);
    if (patient) onOpenPatient(patient);
  };

  return (
    <div className="hkehr-page cdars-page">
      <header className="hkehr-header">
        <div>
          <button className="hkehr-back" onClick={onBack}>{t('cdarsBackToEhrss')}</button>
          <div className="hkehr-title-row">
            <span className="cdars-logo">CDARS</span>
            <h1>{t('cdarsTitle')}</h1>
            <span className="hkehr-mock-badge">{t('mockBadge')}</span>
            <span className="cdars-deid-badge">{t('cdarsDeidBadge')}</span>
          </div>
          <p className="hkehr-subtitle">{t('cdarsSubtitle')}</p>
        </div>
        <LangToggle />
      </header>

      <div className="cdars-grid">
        {/* ── Criteria pane ── */}
        <section className="hkehr-card cdars-criteria">
          <h2>{t('cdarsCriteria')}</h2>

          <label className="hkehr-field">
            <span>{t('cdarsDx')} (ICD-9-CM)</span>
            <select value={criteria.dxCode} onChange={(e) => set('dxCode', e.target.value)}>
              <option value="">— any —</option>
              {ICD9_CATALOG.map((d) => (
                <option key={d.code} value={d.code}>{d.code} · {d.desc}</option>
              ))}
            </select>
          </label>

          <label className="hkehr-field">
            <span>{t('cdarsEpisodeType')}</span>
            <select value={criteria.episodeType} onChange={(e) => set('episodeType', e.target.value as EpisodeType | '')}>
              <option value="">— all —</option>
              {EPISODE_TYPES.map((et) => (
                <option key={et.value} value={et.value}>{et.label}</option>
              ))}
            </select>
          </label>

          <label className="hkehr-field">
            <span>{t('cluster')}</span>
            <select value={criteria.cluster} onChange={(e) => set('cluster', e.target.value)}>
              <option value="">— all clusters —</option>
              {CLUSTERS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>

          <div className="cdars-field-row">
            <label className="hkehr-field">
              <span>{t('sex')}</span>
              <select value={criteria.sex} onChange={(e) => set('sex', e.target.value as 'M' | 'F' | '')}>
                <option value="">—</option>
                <option value="M">M</option>
                <option value="F">F</option>
              </select>
            </label>
            <label className="hkehr-field">
              <span>{t('cdarsAgeMin')}</span>
              <input type="number" value={criteria.ageMin ?? ''} onChange={(e) => set('ageMin', e.target.value === '' ? null : Number(e.target.value))} />
            </label>
            <label className="hkehr-field">
              <span>{t('cdarsAgeMax')}</span>
              <input type="number" value={criteria.ageMax ?? ''} onChange={(e) => set('ageMax', e.target.value === '' ? null : Number(e.target.value))} />
            </label>
          </div>

          <div className="cdars-field-row">
            <label className="hkehr-field">
              <span>{t('cdarsAdmittedFrom')}</span>
              <input type="date" value={criteria.admittedFrom} onChange={(e) => set('admittedFrom', e.target.value)} />
            </label>
            <label className="hkehr-field">
              <span>{t('cdarsAdmittedTo')}</span>
              <input type="date" value={criteria.admittedTo} onChange={(e) => set('admittedTo', e.target.value)} />
            </label>
          </div>

          <label className="cdars-check">
            <input type="checkbox" checked={criteria.deathsOnly} onChange={(e) => set('deathsOnly', e.target.checked)} />
            <span>{t('cdarsDeathsOnly')}</span>
          </label>

          <button className="hkehr-btn hkehr-btn--primary cdars-extract" onClick={handleExtract}>
            {t('cdarsExtract')}
          </button>
        </section>

        {/* ── Results: aggregate counts + de-identified line-listing ── */}
        <section className="hkehr-card cdars-results">
          <h2>{t('cdarsLineListing')}</h2>
          {extracted === null ? (
            <p className="hkehr-empty">{t('cdarsRunHint')}</p>
          ) : (
            <>
              <div className="cdars-counts">
                <div><strong>{counts!.patients}</strong><span>{t('cdarsDistinctKeys')}</span></div>
                <div><strong>{counts!.episodes}</strong><span>{t('cdarsEpisodes')}</span></div>
                <div><strong>{counts!.deaths}</strong><span>{t('cdarsDeaths')}</span></div>
              </div>
              <div className="cdars-table-wrap">
                <table className="cdars-table">
                  <thead>
                    <tr>
                      <th>Ref. Key</th>
                      <th>Sex</th>
                      <th>Age</th>
                      <th>Type</th>
                      <th>Adm. Date</th>
                      <th>Cluster/Hosp</th>
                      <th>Spec</th>
                      <th>ICD-9-CM</th>
                      <th>Drug (BNF)</th>
                      <th>Lab</th>
                      <th>Death</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {extracted.map((e) => (
                      <tr key={e.referenceKey + e.admissionDate} className={e.death ? 'cdars-row--death' : ''}>
                        <td className="hkehr-mono">{e.referenceKey}</td>
                        <td>{e.sex}</td>
                        <td>{e.age}</td>
                        <td>{e.episodeType}</td>
                        <td className="hkehr-mono">{e.admissionDate}</td>
                        <td>{e.cluster}/{e.hospital}</td>
                        <td>{e.specialty}</td>
                        <td className="hkehr-mono" title={e.dxDesc}>{e.dxCode}</td>
                        <td title={`BNF ${e.bnf}`}>{e.drug}</td>
                        <td className="hkehr-mono">{e.labTest} {e.labValue}</td>
                        <td>{e.death ? `✝ ${e.deathDate}` : '—'}</td>
                        <td>
                          {e.linkedHkid && (
                            <button className="cdars-link" onClick={() => handleReidentify(e)} title={t('cdarsReidentifyNote')}>
                              {t('cdarsReidentify')}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {extracted.length === 0 && (
                      <tr><td colSpan={12} className="hkehr-empty">0 episodes</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="cdars-footnote">{t('cdarsFootnote')}</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
