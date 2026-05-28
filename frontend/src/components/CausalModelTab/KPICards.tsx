import { usePatientState } from '../../hooks/usePatientState';
import { getTreatmentDef } from '../../data/dag';
import type { ExtendedOutcomes } from '../../types';
import './KPICards.css';

interface KPICardsProps {
  outcomes: ExtendedOutcomes;
  treatmentId: string;
  compareTreatmentId?: string;
  loading?: boolean;
}

function ConfidenceBadge({ confidence }: { confidence: 'high' | 'moderate' | 'low' }) {
  return (
    <span className={`kpi__confidence kpi__confidence--${confidence}`}>
      {confidence === 'high' ? 'High Confidence' : confidence === 'moderate' ? 'Moderate Confidence' : 'Low Confidence'}
    </span>
  );
}

// F7/F24: pairs of arms where the empirical overlap is too low for the
// estimate to be a true ATE rather than an extrapolation.
// Values come from data/diagnostics/overlap/<arm_a>v<arm_b>/summary.json
const LOW_OVERLAP_PAIRS: Record<string, string> = {
  'continue|deescalate': 'Continue vs De-escalate overlap is only 17%. The estimate is largely an extrapolation — interpret cautiously.',
  'deescalate|continue': 'Continue vs De-escalate overlap is only 17%. The estimate is largely an extrapolation — interpret cautiously.',
};

export function KPICards({ outcomes, treatmentId, compareTreatmentId, loading }: KPICardsProps) {
  const treatDef = getTreatmentDef(treatmentId);
  const compareLabel = compareTreatmentId
    ? getTreatmentDef(compareTreatmentId).chipLabel
    : 'No treatment';

  const overlapKey = compareTreatmentId ? `${treatmentId}|${compareTreatmentId}` : '';
  const overlapWarning = LOW_OVERLAP_PAIRS[overlapKey];
  const oodWarning = outcomes.ood?.outOfDistribution;

  const effect = outcomes.effect;
  const effectLabel = effect < 0
    ? `Reduces mortality by ${Math.abs(effect).toFixed(1)} pp`
    : effect > 0
    ? `Increases mortality by ${Math.abs(effect).toFixed(1)} pp`
    : 'No effect on mortality';
  const effectClass = effect < 0 ? 'kpi__effect--benefit' : effect > 0 ? 'kpi__effect--harm' : 'kpi__effect--neutral';

  if (loading) {
    return (
      <div className="kpi kpi--loading">
        <div className="kpi__spinner" />
        <span className="kpi__loading-text">Recalculating…</span>
      </div>
    );
  }

  return (
    <div className="kpi">
      {oodWarning && (
        <div className="kpi__warning kpi__warning--ood">
          <span className="kpi__warning-icon">!</span>
          <span className="kpi__warning-text">
            This patient's profile is unusual compared to the training cohort
            (Mahalanobis distance {outcomes.ood?.mahalanobis.toFixed(1)} vs
            training p99 {outcomes.ood?.trainingP99.toFixed(1)}). The estimate
            is an <strong>extrapolation</strong>.
          </span>
        </div>
      )}
      {overlapWarning && (
        <div className="kpi__warning kpi__warning--overlap">
          <span className="kpi__warning-icon">!</span>
          <span className="kpi__warning-text">{overlapWarning}</span>
        </div>
      )}
      <div className="kpi__effect-box">
        <div className="kpi__effect-header">
          <span className="kpi__effect-title">Treatment Effect</span>
          <ConfidenceBadge confidence={outcomes.confidence} />
        </div>
        <div className={`kpi__effect-value ${effectClass}`}>{effectLabel}</div>
        <div className="kpi__effect-sub">
          <span style={{ color: treatDef.color }}>{treatDef.chipLabel}</span>
          {' vs. '}
          <span>{compareLabel}</span>
          {outcomes.ate !== undefined && (
            <span className="kpi__ate">
              {' '}(ATE {outcomes.ate > 0 ? '+' : ''}{outcomes.ate.toFixed(1)} pp
              [{outcomes.ateLowerBound.toFixed(1)}, {outcomes.ateUpperBound.toFixed(1)}])
            </span>
          )}
        </div>
      </div>

      <div className="kpi__cards">
        <div className="kpi__card kpi__card--treatment">
          <div className="kpi__card-label" style={{ color: treatDef.color }}>{treatDef.chipLabel}</div>
          <div className="kpi__card-value">{outcomes.withTreatment.toFixed(1)}%</div>
          <div className="kpi__card-sub">28-day mortality</div>
        </div>
        <div className="kpi__card kpi__card--alt">
          <div className="kpi__card-label">{compareLabel}</div>
          <div className="kpi__card-value">{outcomes.withoutTreatment.toFixed(1)}%</div>
          <div className="kpi__card-sub">28-day mortality</div>
        </div>
      </div>

      {(outcomes.vfdDays !== undefined || outcomes.cdiffRisk !== undefined) && (
        <div className="kpi__secondary">
          <div className="kpi__secondary-title">Secondary Outcomes</div>
          <div className="kpi__secondary-grid">
            {outcomes.vfdDays !== undefined && (
              <div className="kpi__secondary-item">
                <span className="kpi__secondary-label">Ventilator-free days</span>
                <span className="kpi__secondary-value">{outcomes.vfdDays}d</span>
              </div>
            )}
            {outcomes.icuLosDays !== undefined && (
              <div className="kpi__secondary-item">
                <span className="kpi__secondary-label">Est. ICU stay</span>
                <span className="kpi__secondary-value">{outcomes.icuLosDays}d</span>
              </div>
            )}
            {outcomes.cdiffRisk !== undefined && (
              <div className="kpi__secondary-item">
                <span className="kpi__secondary-label">C. diff risk</span>
                <span className="kpi__secondary-value kpi__secondary-value--risk">{outcomes.cdiffRisk.toFixed(1)}%</span>
              </div>
            )}
            {outcomes.resistanceRisk !== undefined && (
              <div className="kpi__secondary-item">
                <span className="kpi__secondary-label">AMR risk</span>
                <span className="kpi__secondary-value kpi__secondary-value--risk">{outcomes.resistanceRisk.toFixed(1)}%</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function TreatmentSelector({
  activeTreatmentId,
  onSelect,
}: {
  activeTreatmentId: string;
  onSelect: (id: string) => void;
}) {
  const treatments = [
    { id: 'continue', label: 'Continue', color: '#e85c4a' },
    { id: 'deescalate', label: 'De-escalate', color: '#2e8bff' },
    { id: 'cease', label: 'Cease', color: '#37d6a0' },
  ];

  return (
    <div className="treatment-selector">
      <span className="treatment-selector__label">Treatment decision:</span>
      <div className="treatment-selector__options">
        {treatments.map(t => (
          <button
            key={t.id}
            className={`treatment-selector__btn ${activeTreatmentId === t.id ? 'treatment-selector__btn--active' : ''}`}
            style={{
              '--t-color': t.color,
              borderColor: activeTreatmentId === t.id ? t.color : undefined,
              color: activeTreatmentId === t.id ? t.color : undefined,
            } as React.CSSProperties}
            onClick={() => onSelect(t.id)}
          >
            <span
              className="treatment-selector__dot"
              style={{ background: t.color }}
            />
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function BaselineKPI() {
  const state = usePatientState();
  return (
    <div className="kpi kpi--baseline">
      <div className="kpi__baseline-text">
        Add the treatment node to the graph to see outcome estimates for this patient profile.
      </div>
      <div className="kpi__baseline-profile">
        <span>SOFA {state.sofa}</span>
        <span>·</span>
        <span>CRP {state.crp} mg/L</span>
        <span>·</span>
        <span>Culture: {state.cultureResult}</span>
      </div>
    </div>
  );
}
