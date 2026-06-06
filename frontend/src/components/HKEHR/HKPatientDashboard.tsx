import { useMemo } from 'react';
import type { HKPatient } from '../../data/hkPatients';
import { haHospitals } from '../../data/hkPatients';
import { ARMS, bestArm, type Arm, type ArmPredictions } from '../../utils/prediction';
import type { AssistantAction } from '../../utils/assistant';
import { useLang, pick, LangToggle } from '../../i18n';
import { ChatBot } from './ChatBot';
import './HKEHR.css';

/* ────────────────────────────────────────────────────────────────────────
   Retrieved-record dashboard — the lean web surface. Voice lives on the
   glasses (tap the HUD to talk); here: prediction + vitals up front,
   allergy banner, eHRSS record domains collapsed behind toggles, chatbot
   as the typed fallback.
   ──────────────────────────────────────────────────────────────────────── */

interface HKPatientDashboardProps {
  patient: HKPatient;
  preds: ArmPredictions | null;
  onBack: () => void;
  onAction: (action: AssistantAction) => void;
  onOpenHud: () => void;
}

export function HKPatientDashboard({ patient, preds, onBack, onAction, onOpenHud }: HKPatientDashboardProps) {
  const { lang, t } = useLang();
  const zh = lang === 'zh-HK';
  const pickL = pick(lang);

  const hospital = haHospitals.find((h) => h.code === patient.hospitalCode)!;

  const armLabel: Record<Arm, string> = {
    continue: t('armContinue'),
    deescalate: t('armDeescalate'),
    cease: t('armCease'),
  };

  const best: Arm | null = preds ? bestArm(preds.values) : null;

  const pr = patient.profile;
  const vitals: Array<[string, string]> = useMemo(() => [
    ['SOFA', `${pr.sofa}/24`],
    ['SAPS II', `${pr.sapsii}`],
    [zh ? '乳酸' : 'Lactate', `${pr.lactate} mmol/L`],
    ['MAP', `${pr.map} mmHg`],
    [zh ? '心率' : 'HR', `${pr.heartRate}/min`],
    ['SpO₂', `${pr.spo2}%`],
    [zh ? '體溫' : 'Temp', `${pr.temperature}°C`],
    [zh ? '升壓藥' : 'Vasopressors', pr.vaso === 'YES' ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No')],
    [zh ? '呼吸機' : 'Ventilation', pr.ventilation === 'YES' ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No')],
  ], [pr, zh]);

  return (
    <div className="hkehr-page hkehr-page--dash">
      <header className="hkehr-header">
        <div>
          <button className="hkehr-back" onClick={onBack}>{t('back')}</button>
          <div className="hkehr-title-row">
            <h1>{patient.nameEn} <span className="hkehr-name-zh">{patient.nameZh}</span></h1>
            <span className="hkehr-chip">{hospital.clusterCode}/{patient.hospitalCode} · {pickL(hospital.name)}</span>
            <span className="hkehr-chip hkehr-chip--dim">{patient.sourceSystem}</span>
          </div>
          <p className="hkehr-subtitle">{pickL(patient.subtitle)} · {pickL(patient.ward)}</p>
        </div>
        <div className="hkehr-header-actions">
          <button className="hkehr-btn" onClick={onOpenHud}>{t('glassesHud')}</button>
          <LangToggle />
        </div>
      </header>

      {/* Allergies must never hide behind a toggle */}
      {patient.allergies.length > 0 && (
        <div className="hkehr-allergy-banner">
          ⚠ {t('domainAllergies')}: {patient.allergies.map((a) => pickL(a.display)).join(' · ')}
        </div>
      )}

      <div className="hkehr-dash-grid">
        {/* ── Left: prediction + vitals (primary) ── */}
        <div className="hkehr-dash-side">
          <section className="hkehr-card hkehr-pred">
            <h2>{t('predictionTitle')}</h2>
            <p className="hkehr-pred__sub">{t('predictionSub')}</p>
            <div className={`hkehr-pred__source ${preds?.live ? 'live' : ''}`}>
              {preds === null ? t('chatThinking') : preds.live ? `● ${t('liveModel')}` : `○ ${t('fallbackModel')}`}
            </div>
            <div className="hkehr-arms">
              {ARMS.map((arm) => (
                <div key={arm} className={`hkehr-arm hkehr-arm--${arm} ${best === arm ? 'hkehr-arm--best' : ''}`}>
                  <span className="hkehr-arm__label">{armLabel[arm]}</span>
                  <span className="hkehr-arm__value">
                    {preds ? `${preds.values[arm]}%` : '…'}
                  </span>
                  <span className="hkehr-arm__unit">{t('mortality')}</span>
                  {best === arm && <span className="hkehr-arm__badge">{t('recommended')}</span>}
                </div>
              ))}
            </div>
            <p className="hkehr-pred__rec">{pickL(patient.outcomes.recommendation)}</p>
          </section>

          <section className="hkehr-card">
            <h2>{t('vitals')}</h2>
            <div className="hkehr-vitals">
              {vitals.map(([label, value]) => (
                <div key={label} className="hkehr-vital">
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
          </section>

          <ChatBot patient={patient} basePredictions={preds} onAction={onAction} />
        </div>

        {/* ── Right: eHRSS record, collapsed by default (lean) ── */}
        <div className="hkehr-dash-record">
          <section className="hkehr-card">
            <h2>{t('retrievedRecord')} · {t('domainPmi')}</h2>
            <dl className="hkehr-pmi">
              <div><dt>{t('hkid')}</dt><dd>{patient.hkid}</dd></div>
              <div><dt>{t('nameEn')}</dt><dd>{patient.nameEn}</dd></div>
              <div><dt>{t('nameZh')}</dt><dd>{patient.nameZh}</dd></div>
              <div><dt>{t('ccc')}</dt><dd className="hkehr-mono">{patient.ccc}</dd></div>
              <div><dt>{t('dob')}</dt><dd>{patient.dob}</dd></div>
              <div><dt>{t('sex')}</dt><dd>{patient.sex === 'F' ? t('female') : t('male')}</dd></div>
              <div><dt>{t('ward')}</dt><dd>{pickL(patient.ward)}</dd></div>
            </dl>
          </section>

          <details className="hkehr-card hkehr-collapse">
            <summary>{t('domainDiagnoses')} <span className="hkehr-count">{patient.diagnoses.length}</span></summary>
            <ul className="hkehr-coded">
              {patient.diagnoses.map((d) => (
                <li key={d.code}>
                  <span className="hkehr-code">{d.system} {d.code}</span>
                  <span>{pickL(d.display)}</span>
                </li>
              ))}
            </ul>
          </details>

          <details className="hkehr-card hkehr-collapse">
            <summary>{t('domainMeds')} <span className="hkehr-count">{patient.medications.length}</span></summary>
            <ul className="hkehr-coded">
              {patient.medications.map((m) => (
                <li key={m.code}>
                  <span className="hkehr-code">{m.system} {m.code}</span>
                  <span>{pickL(m.display)}</span>
                </li>
              ))}
            </ul>
          </details>

          <details className="hkehr-card hkehr-collapse">
            <summary>{t('domainLabs')} <span className="hkehr-count">{patient.labs.length}</span></summary>
            <table className="hkehr-labs">
              <tbody>
                {patient.labs.map((l) => (
                  <tr key={l.loinc + l.value}>
                    <td className="hkehr-code">LOINC {l.loinc}</td>
                    <td>{pickL(l.name)}</td>
                    <td className="hkehr-mono">{l.value} {l.unit}</td>
                    <td>{l.flag && <span className={`hkehr-flag hkehr-flag--${l.flag.toLowerCase()}`}>{l.flag}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <details className="hkehr-card hkehr-collapse">
            <summary>{t('domainAllergies')} <span className="hkehr-count">{patient.allergies.length}</span></summary>
            {patient.allergies.length === 0 ? (
              <p className="hkehr-empty">{zh ? '無已知過敏' : 'No known allergies'}</p>
            ) : (
              <ul className="hkehr-coded">
                {patient.allergies.map((a) => (
                  <li key={a.code}>
                    <span className="hkehr-code">{a.system} {a.code}</span>
                    <span className="hkehr-allergy">{pickL(a.display)}</span>
                  </li>
                ))}
              </ul>
            )}
          </details>

          <details className="hkehr-card hkehr-collapse">
            <summary>{t('domainEncounters')} <span className="hkehr-count">{patient.encounters.length}</span></summary>
            <ul className="hkehr-coded">
              {patient.encounters.map((e) => (
                <li key={e.date + e.facility}>
                  <span className="hkehr-code">{e.date} · {e.facility}</span>
                  <span>{pickL(e.type)}</span>
                </li>
              ))}
            </ul>
          </details>
        </div>
      </div>

    </div>
  );
}
