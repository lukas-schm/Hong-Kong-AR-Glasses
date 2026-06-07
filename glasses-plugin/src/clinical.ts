/* ────────────────────────────────────────────────────────────────────────
   Red flags + decision derivation — port of the logic in GlassesHUD.tsx
   (deriveRedFlags / deriveDecisions), operating directly on the CDARS
   server record. Same thresholds, no charts: the G2 renders plain text.
   ──────────────────────────────────────────────────────────────────────── */
import type { Arm, PatientRecord } from './cdars';

export interface RedFlag { label: string; value: string; severity: 'crit' | 'warn' }

export function deriveRedFlags(p: PatientRecord): RedFlag[] {
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

export interface DecisionOption { key: string; label: string; mortality: number }
export interface Decision { id: 'abx' | 'fluids' | 'pressors'; axis: string; options: DecisionOption[]; recKey: string }

export function deriveDecisions(p: PatientRecord, live?: Record<Arm, number> | null): Decision[] {
  const pr = p.profile;
  const o = {
    continue: live?.continue ?? p.outcomes.continue ?? 0,
    deescalate: live?.deescalate ?? p.outcomes.deescalate ?? 0,
    cease: live?.cease ?? p.outcomes.cease ?? 0,
    recommendedAction: p.outcomes.recommendedAction,
  };
  const base = o[o.recommendedAction];

  const abx: Decision = {
    id: 'abx', axis: 'Antibiotics', recKey: o.recommendedAction,
    options: [
      { key: 'continue', label: 'Keep', mortality: o.continue },
      { key: 'deescalate', label: 'Narrow', mortality: o.deescalate },
      { key: 'cease', label: 'Stop', mortality: o.cease },
    ],
  };

  const hypoperfused = (pr.map ?? 99) < 65 || (pr.lactate ?? 0) >= 4;
  const overloaded = (pr.aki ?? 0) >= 2 || (pr.urineOutput ?? 9999) < 600;
  const fluidsRec = hypoperfused ? 'bolus' : overloaded ? 'restrict' : 'maintain';
  const fluids: Decision = {
    id: 'fluids', axis: 'Fluids', recKey: fluidsRec,
    options: [
      { key: 'bolus', label: 'More', mortality: base + (hypoperfused ? -4 : 5) },
      { key: 'maintain', label: 'Steady', mortality: base + (hypoperfused ? 2 : overloaded ? 1 : -2) },
      { key: 'restrict', label: 'Less', mortality: base + (overloaded ? -3 : hypoperfused ? 7 : 1) },
    ],
  };

  const onVaso = pr.vaso === 'YES';
  const hypotensive = (pr.map ?? 99) < 65;
  const pressorsRec = onVaso && hypotensive ? 'escalate' : onVaso ? 'wean' : 'none';
  const pressors: Decision = {
    id: 'pressors', axis: 'BP support', recKey: pressorsRec,
    options: [
      { key: 'escalate', label: 'More', mortality: base + (hypotensive ? -5 : 4) },
      { key: 'wean', label: 'Less', mortality: base + (onVaso && !hypotensive ? -2 : 6) },
      { key: 'none', label: 'None', mortality: base + (onVaso ? 9 : -1) },
    ],
  };

  return [abx, fluids, pressors];
}
