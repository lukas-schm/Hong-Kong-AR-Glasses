import { useEffect, useMemo, useRef, useState } from 'react';
import { haHospitals, hkPatients, findPatientByHkid, type HKPatient } from '../../data/hkPatients';
import { useLang, LangToggle, pick, type TKey } from '../../i18n';
import './HKEHR.css';

/* ────────────────────────────────────────────────────────────────────────
   Mocked eHRSS (醫健通) retrieval flow:
   1. pick HA cluster + hospital (source facility, HA-CMS)
   2. look up patient by HKID — or pick from current ICU admissions
   3. sharing-consent gate, then per-domain retrieval animation
   ──────────────────────────────────────────────────────────────────────── */

interface EHRSelectPageProps {
  onRetrieved: (patient: HKPatient) => void;
  onOpenHud: () => void;
  onOpenCdars: () => void;
}

const DOMAIN_KEYS: TKey[] = [
  'domainPmi',
  'domainDiagnoses',
  'domainMeds',
  'domainLabs',
  'domainAllergies',
  'domainEncounters',
];

export function EHRSelectPage({ onRetrieved, onOpenHud, onOpenCdars }: EHRSelectPageProps) {
  const { lang, t } = useLang();
  const pickL = pick(lang);

  const [hospitalCode, setHospitalCode] = useState('QEH');
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<HKPatient | null>(null);
  const [retrievingStep, setRetrievingStep] = useState(-1); // -1 idle, 0..n during retrieval
  // Single cancellable timer driving the staged retrieval animation.
  const timerRef = useRef<number | null>(null);
  useEffect(() => () => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
  }, []);

  const hospital = haHospitals.find((h) => h.code === hospitalCode)!;
  const inpatients = useMemo(
    () => hkPatients.filter((p) => p.hospitalCode === hospitalCode),
    [hospitalCode],
  );
  const searchHit = useMemo(
    () => (searched ? findPatientByHkid(query, hospitalCode) : undefined),
    [searched, query, hospitalCode],
  );

  const retrieving = retrievingStep >= 0;

  const handleSearch = () => {
    if (retrieving) return;
    setSearched(true);
    const hit = findPatientByHkid(query, hospitalCode);
    if (hit) setSelected(hit);
  };

  const handleRetrieve = (patient: HKPatient) => {
    if (retrieving) return; // ignore re-entry while a retrieval is running
    setSelected(patient);
    setRetrievingStep(0);
    // Step through the eHRSS data domains, then hand off.
    let step = 0;
    timerRef.current = window.setInterval(() => {
      step += 1;
      if (step > DOMAIN_KEYS.length) {
        window.clearInterval(timerRef.current!);
        timerRef.current = null;
        onRetrieved(patient);
      } else {
        setRetrievingStep(step);
      }
    }, 350);
  };

  return (
    <div className="hkehr-page">
      <header className="hkehr-header">
        <div>
          <div className="hkehr-title-row">
            <span className="hkehr-logo">醫健通</span>
            <h1>{t('ehrssTitle')}</h1>
            <span className="hkehr-mock-badge">{t('mockBadge')}</span>
          </div>
          <p className="hkehr-subtitle">{t('ehrssSubtitle')}</p>
        </div>
        <div className="hkehr-header-actions">
          <button
            className="hkehr-btn"
            onClick={() => window.open(`${window.location.pathname}#monitor`, 'cdss-monitor', 'width=1100,height=720')}
          >
            {t('openMonitor')}
          </button>
          <button className="hkehr-btn cdars-nav-btn" onClick={onOpenCdars}>{t('cdarsOpen')}</button>
          <button className="hkehr-btn" onClick={onOpenHud}>{t('glassesHud')}</button>
          <LangToggle />
        </div>
      </header>

      <div className="hkehr-grid">
        {/* ── Step 1: facility ── */}
        <section className="hkehr-card">
          <h2>{t('step1')}</h2>
          <label className="hkehr-field">
            <span>{t('cluster')} / {t('hospital')}</span>
            <select value={hospitalCode} onChange={(e) => { setHospitalCode(e.target.value); setSelected(null); setSearched(false); }}>
              {haHospitals.map((h) => (
                <option key={h.code} value={h.code}>
                  {h.clusterCode} · {pickL(h.name)} ({h.code})
                </option>
              ))}
            </select>
          </label>
          <div className="hkehr-facility-meta">
            <span className="hkehr-chip">{pickL(hospital.cluster)}</span>
            <span className="hkehr-chip">{t('sourceSystem')}: HA-CMS</span>
            <span className="hkehr-chip hkehr-chip--dim">HL7 v2 · HKCTT</span>
          </div>
        </section>

        {/* ── Step 2: patient lookup ── */}
        <section className="hkehr-card">
          <h2>{t('step2')}</h2>
          <label className="hkehr-field">
            <span>{t('hkidLabel')}</span>
            <div className="hkehr-search-row">
              <input
                value={query}
                placeholder={t('hkidPlaceholder')}
                onChange={(e) => { setQuery(e.target.value); setSearched(false); }}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
              <button className="hkehr-btn" onClick={handleSearch}>{t('searchBtn')}</button>
            </div>
          </label>
          {searched && !searchHit && <p className="hkehr-nomatch">{t('noMatch')}</p>}

          <div className="hkehr-inpatients-label">
            {t('inpatients')} {pickL(hospital.name)}
          </div>
          <ul className="hkehr-patient-list">
            {inpatients.length === 0 && <li className="hkehr-empty">—</li>}
            {inpatients.map((p) => (
              <li key={p.hkid}>
                <button
                  className={`hkehr-patient ${selected?.hkid === p.hkid ? 'hkehr-patient--active' : ''}`}
                  onClick={() => !retrieving && setSelected(p)}
                >
                  <span className="hkehr-patient__name">
                    {p.nameEn} <span className="hkehr-patient__zh">{p.nameZh}</span>
                  </span>
                  <span className="hkehr-patient__meta">{p.hkid} · {pickL(p.ward)}</span>
                  <span className="hkehr-patient__sub">{pickL(p.subtitle)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {/* ── Step 3: consent + retrieval ── */}
        <section className="hkehr-card">
          <h2>{t('step3')}</h2>
          {selected ? (
            <>
              <div className="hkehr-consent">
                <span className="hkehr-consent__icon">✓</span>
                <div>
                  <strong>{t('consentTitle')}</strong>
                  <p>{t('consentBody')}</p>
                </div>
              </div>
              <div className="hkehr-selected">
                <span>{selected.nameEn} {selected.nameZh}</span>
                <span className="hkehr-selected__id">{selected.hkid} · {selected.hospitalCode}</span>
              </div>
              {retrievingStep < 0 ? (
                <button className="hkehr-btn hkehr-btn--primary" onClick={() => handleRetrieve(selected)}>
                  {t('retrieveBtn')}
                </button>
              ) : (
                <div className="hkehr-domains">
                  <div className="hkehr-retrieving">{t('retrieving')}</div>
                  <ul>
                    {DOMAIN_KEYS.map((key, i) => (
                      <li key={key} className={i < retrievingStep ? 'done' : i === retrievingStep ? 'active' : ''}>
                        <span className="hkehr-domain-state">{i < retrievingStep ? '✓' : i === retrievingStep ? '⟳' : '·'}</span>
                        {t(key)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <p className="hkehr-empty">—</p>
          )}
        </section>
      </div>
    </div>
  );
}
