import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLang } from '../i18n';
import { useVoice } from '../utils/voice';
import { bus, type BusActivity, type BusEvent, type BusRole } from '../utils/bus';
import { useHudSync, selectPatient as syncSelect } from '../utils/hudSync';
import {
  fetchActivePatients, fetchPatient, fetchArmPredictions, fetchCohortOutcomes,
  type CohortOutcomes,
} from '../api/cdars';
import { sendAgentCommand } from '../utils/agentClient';
import { hkToExemplar } from '../utils/hkAdapter';
import { cachedArmValues, predictAllArms, type ArmPredictions } from '../utils/prediction';
import type { HKPatient } from '../data/hkPatients';
import type { ExemplarPatient } from '../data/exemplarPatients';
import type { AgentStep, PatientMenuItem } from '../components/GlassesHUD/GlassesHUD';

/* ────────────────────────────────────────────────────────────────────────
   The shared CDSS session — one engine behind both the glasses (#glasses)
   and the monitor (#monitor). It owns:

     · the active CDARS worklist (live; refetched on any data-change)
     · the current patient (driven by the synced hudSync.referenceKey)
     · live model predictions + territory-wide cohort outcomes
     · the agent: voice → /agent/command → reply, with bus activity steps
     · presence / connection status

   Both surfaces render the same GlassesHUD from this, so they mirror live.
   ──────────────────────────────────────────────────────────────────────── */

const keyOf = (p: HKPatient) => p.referenceKey ?? p.hkid;

async function getPredictions(p: HKPatient, signal?: AbortSignal): Promise<ArmPredictions> {
  if (p.referenceKey) {
    const live = await fetchArmPredictions(p.referenceKey, signal);
    if (live) return live;
  }
  try {
    return await predictAllArms(p, signal);
  } catch {
    return { values: cachedArmValues(p), live: false };
  }
}

export interface CdssSession {
  lang: 'en' | 'zh-HK';
  setLang: (l: 'en' | 'zh-HK') => void;
  patients: HKPatient[];
  menuItems: PatientMenuItem[];
  current: HKPatient | null;
  exemplar: ExemplarPatient | null;
  predictions: ArmPredictions | null;
  cohort: CohortOutcomes | null;
  steps: AgentStep[];
  assistant: {
    supported: boolean; listening: boolean; interim: string;
    lastUtterance: string | null; reply: string | null; busy: boolean;
    error: import('../utils/voice').VoiceError; onTap: () => void;
  };
  presence: string[];
  connected: boolean;
  selectPatient: (key: string) => void;
  sendText: (text: string) => Promise<void>;
}

export function useCdssSession(role: BusRole): CdssSession {
  const { lang, setLang } = useLang();
  const sync = useHudSync();

  const [patients, setPatients] = useState<HKPatient[]>([]);
  const [predictions, setPredictions] = useState<ArmPredictions | null>(null);
  const [cohort, setCohort] = useState<CohortOutcomes | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [presence, setPresence] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);

  const [lastUtterance, setLastUtterance] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /* ── bus lifecycle ── */
  useEffect(() => {
    bus.start(role);
    const offP = bus.onPresence(setPresence);
    const offS = bus.onStatus(setConnected);
    return () => { offP(); offS(); };
  }, [role]);

  /* ── load the active worklist ── */
  const reloadActive = useCallback(async (signal?: AbortSignal) => {
    const list = await fetchActivePatients(signal);
    if (!signal?.aborted) setPatients(list);
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    reloadActive(ctrl.signal).catch(() => {});
    return () => ctrl.abort();
  }, [reloadActive]);

  /* ── current patient resolved from the synced key ── */
  const current = useMemo(() => {
    if (!sync.referenceKey) return null;
    return patients.find((p) => keyOf(p) === sync.referenceKey
      || p.hkid === sync.referenceKey || p.referenceKey === sync.referenceKey) ?? null;
  }, [patients, sync.referenceKey]);

  /* ── predictions + cohort for the current patient ── */
  const refreshModel = useCallback((p: HKPatient | null) => {
    if (!p) { setPredictions(null); setCohort(null); return; }
    const ctrl = new AbortController();
    setPredictions(null); setCohort(null);
    getPredictions(p, ctrl.signal).then((pr) => { if (!ctrl.signal.aborted) setPredictions(pr); }).catch(() => {});
    if (p.referenceKey) {
      fetchCohortOutcomes(p.referenceKey, ctrl.signal)
        .then((c) => { if (!ctrl.signal.aborted) setCohort(c); }).catch(() => {});
    }
    return () => ctrl.abort();
  }, []);

  useEffect(() => refreshModel(current), [current?.referenceKey, current?.hkid, refreshModel, current]);

  /* ── live activity steps + data-change refetch ── */
  const currentKeyRef = useRef<string | null>(null);
  currentKeyRef.current = current ? keyOf(current) : null;

  useEffect(() => {
    const off = bus.subscribe((ev: BusEvent) => {
      if (ev.type === 'activity') {
        const a = ev as BusActivity;
        const text = lang === 'zh-HK' && a.textZh ? a.textZh : a.text;
        setSteps((prev) => [...prev.slice(-15), { kind: a.kind, text, ok: a.ok }]);
        if (a.kind === 'reply') setReply(text);
      } else if (ev.type === 'data-change') {
        const rk = (ev as { referenceKey: string }).referenceKey;
        fetchPatient(rk).then((fresh) => {
          if (!fresh) return;
          setPatients((prev) => prev.map((p) => (keyOf(p) === rk || p.referenceKey === rk ? fresh : p)));
          if (currentKeyRef.current === rk || fresh.referenceKey === currentKeyRef.current) refreshModel(fresh);
        }).catch(() => {});
      }
    });
    return off;
  }, [lang, refreshModel]);

  /* ── selecting a patient (manual menu / speech-resolved) ── */
  const selectPatient = useCallback((key: string) => {
    syncSelect(key);
    const p = patients.find((q) => keyOf(q) === key || q.hkid === key);
    bus.publishActivity({ kind: 'tool', text: `Opened ${p?.nameEn ?? key} on the glasses`,
      textZh: `喺眼鏡開啟 ${p?.nameZh ?? key}`, referenceKey: key });
  }, [patients]);

  /* ── the agent: send an utterance ── */
  const ctxRef = useRef<{ current: HKPatient | null; predictions: ArmPredictions | null }>({ current: null, predictions: null });
  ctxRef.current = { current, predictions };

  const sendText = useCallback(async (text: string) => {
    if (!text.trim()) return;
    setLastUtterance(text);
    setReply(null);
    setBusy(true);
    try {
      const { current: cur, predictions: pr } = ctxRef.current;
      const res = await sendAgentCommand(text, {
        referenceKey: cur ? keyOf(cur) : null,
        source: role === 'glasses' ? 'glasses' : 'voice',
        lang,
        fallback: { patient: cur, basePredictions: pr },
      });
      setReply(res.reply);
      if (res.select) syncSelect(res.select);
      // Offline writes don't round-trip through the server → mutate locally.
      const localWrites = (res as { localWrites?: Array<{ key: keyof HKPatient['profile']; value: number }> }).localWrites;
      if (localWrites && cur) {
        setPatients((prev) => prev.map((p) => {
          if (keyOf(p) !== keyOf(cur)) return p;
          const profile = { ...p.profile } as Record<string, unknown>;
          localWrites.forEach((w) => { profile[w.key as string] = w.value; });
          return { ...p, profile: profile as HKPatient['profile'] };
        }));
      }
      if (res.changed && res.offline && cur) refreshModel(cur);
    } finally {
      setBusy(false);
    }
  }, [lang, role, refreshModel]);

  /* ── voice input ── */
  const voice = useVoice(lang, sendText);
  // Clear the conversation when the patient changes.
  useEffect(() => { setReply(null); setLastUtterance(null); setSteps([]); }, [current?.referenceKey, current?.hkid]);

  const menuItems: PatientMenuItem[] = useMemo(() => patients.map((p) => ({
    referenceKey: keyOf(p),
    name: lang === 'zh-HK' ? p.nameZh || p.nameEn : p.nameEn,
    subtitle: lang === 'zh-HK' ? p.subtitle.zh : p.subtitle.en,
    hospital: p.hospitalCode,
    arm: p.outcomes.recommendedAction,
  })), [patients, lang]);

  const exemplar = useMemo(
    () => (current ? hkToExemplar(current, lang, predictions ?? undefined) : null),
    [current, lang, predictions],
  );

  return {
    lang, setLang, patients, menuItems, current, exemplar, predictions, cohort, steps,
    assistant: {
      supported: voice.supported, listening: voice.listening, interim: voice.interim,
      lastUtterance, reply, busy, error: voice.error, onTap: voice.toggle,
    },
    presence, connected, selectPatient, sendText,
  };
}
