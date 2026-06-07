/* ────────────────────────────────────────────────────────────────────────
   CDARS CDSS on Even G2 — plugin entry point.

   Wires together:
     · the Even App bridge (containers on the glasses, temple gestures, mic)
     · the CDARS bus (mirror-synced select/nav with #monitor and #cdars)
     · the CDARS REST API (worklist, live predictions, cohort, agent)

   Interaction model (temple touchpad):
     worklist page: scroll = move cursor (native) · tap = open patient
     patient page : scroll = cycle decision cards · tap = talk (toggle mic)
                    double-tap = back to worklist
   ──────────────────────────────────────────────────────────────────────── */
import { waitForEvenAppBridge, OsEventTypeList } from '@evenrealities/even_hub_sdk';
import { bus, type BusActivity, type BusEvent } from './bus';
import {
  fetchActivePatients, fetchArmPredictions, fetchCohortOutcomes, fetchPatient,
  sendAgentCommand, type PatientRecord,
} from './cdars';
import { CARD_COUNT, Renderer, type RenderState } from './render';
import { G2Voice } from './voice';
import { mountPhonePanel } from './phonePanel';

const st: RenderState = {
  page: 'worklist',
  patients: [],
  current: null,
  predictions: null,
  cohort: null,
  card: 0,
  connected: false,
  listening: false,
  reply: null,
  lastUtterance: null,
};

const keyOf = (p: PatientRecord) => p.referenceKey ?? p.hkid ?? '';

async function main() {
  const panel = mountPhonePanel();
  const bridge = await waitForEvenAppBridge();
  const renderer = new Renderer(bridge);
  const voice = new G2Voice(bridge);
  panel.log('bridge ready');

  /* ── model context for the current patient ── */
  async function loadModel(p: PatientRecord) {
    st.predictions = null;
    st.cohort = null;
    const key = keyOf(p);
    const [pred, cohort] = await Promise.all([
      fetchArmPredictions(key), fetchCohortOutcomes(key),
    ]);
    if (st.current && keyOf(st.current) === key) {
      st.predictions = pred;
      st.cohort = cohort;
      void renderer.update(st);
    }
  }

  function openPatient(key: string, broadcast: boolean) {
    const p = st.patients.find((q) => keyOf(q) === key || q.hkid === key);
    if (!p) return;
    st.current = p;
    st.page = 'patient';
    st.card = 0;
    st.reply = null;
    st.lastUtterance = null;
    void renderer.render(st);
    void loadModel(p);
    if (broadcast) {
      bus.publishSelect(keyOf(p));
      bus.publishActivity({
        kind: 'tool',
        text: `Opened ${p.nameEn} on the glasses`,
        referenceKey: keyOf(p),
      });
    }
  }

  function backToWorklist(broadcast: boolean) {
    st.page = 'worklist';
    st.current = null;
    void renderer.render(st);
    if (broadcast) bus.publishNav({ menuOpen: true });
  }

  function setCard(card: number, broadcast: boolean) {
    st.card = ((card % CARD_COUNT) + CARD_COUNT) % CARD_COUNT;
    void renderer.update(st);
    if (broadcast) bus.publishNav({ card: st.card });
  }

  /* ── agent: utterance → server → reply ── */
  async function sendText(text: string) {
    st.lastUtterance = text;
    st.reply = '…';
    void renderer.update(st);
    try {
      const res = await sendAgentCommand(text, { referenceKey: st.current ? keyOf(st.current) : null });
      st.reply = res.reply;
      if (res.select) openPatient(res.select, false);
    } catch {
      st.reply = 'agent unreachable';
    }
    void renderer.update(st);
  }

  async function toggleTalk() {
    if (voice.listening) {
      st.listening = false;
      void renderer.update(st);
      const text = await voice.stop();
      if (text) await sendText(text);
      else { st.reply = st.reply ?? 'voice failed — nothing heard / server ASR down'; void renderer.update(st); }
    } else {
      st.listening = await voice.start();
      void renderer.update(st);
    }
  }

  /* ── temple touchpad / mic events ── */
  bridge.onEvenHubEvent((event) => {
    if (event.audioEvent) { voice.onAudio(event.audioEvent.audioPcm); return; }

    if (event.listEvent && st.page === 'worklist') {
      const idx = event.listEvent.currentSelectItemIndex ?? -1;
      const p = st.patients[idx];
      if (event.listEvent.eventType === OsEventTypeList.CLICK_EVENT && p) {
        openPatient(keyOf(p), true);
      } else if (typeof idx === 'number' && idx >= 0) {
        bus.publishNav({ menuOpen: true, menuIndex: idx });
      }
      return;
    }

    if (event.textEvent && st.page === 'patient') {
      switch (event.textEvent.eventType) {
        case OsEventTypeList.CLICK_EVENT: void toggleTalk(); break;
        case OsEventTypeList.DOUBLE_CLICK_EVENT: backToWorklist(true); break;
        case OsEventTypeList.SCROLL_BOTTOM_EVENT: setCard(st.card + 1, true); break;
        case OsEventTypeList.SCROLL_TOP_EVENT: setCard(st.card - 1, true); break;
      }
    }
  });

  /* ── inbound bus events (mirror-sync with monitor/cdars) ── */
  bus.subscribe((ev: BusEvent) => {
    if (ev.type === 'select') {
      openPatient((ev as { referenceKey: string }).referenceKey, false);
    } else if (ev.type === 'nav') {
      const n = ev as { card?: number; menuOpen?: boolean };
      if (n.menuOpen === true && st.page !== 'worklist') backToWorklist(false);
      else if (typeof n.card === 'number') setCard(n.card, false);
    } else if (ev.type === 'activity') {
      const a = ev as BusActivity;
      if (a.kind === 'reply' && a.source !== 'glasses') {
        st.reply = a.text;
        void renderer.update(st);
      }
    } else if (ev.type === 'data-change') {
      const rk = (ev as { referenceKey: string }).referenceKey;
      fetchPatient(rk).then((fresh) => {
        st.patients = st.patients.map((p) => (keyOf(p) === rk ? fresh : p));
        if (st.current && keyOf(st.current) === rk) {
          st.current = fresh;
          void renderer.update(st);
          void loadModel(fresh);
        }
      }).catch(() => {});
    }
  });

  bus.onStatus((connected) => {
    st.connected = connected;
    panel.setConnected(connected);
    void renderer.update(st);
  });
  bus.start();

  /* ── initial worklist ── */
  try {
    st.patients = await fetchActivePatients();
    panel.log(`worklist: ${st.patients.length} active patients`);
  } catch (e) {
    panel.log(`CDARS unreachable: ${String(e)}`);
  }
  await renderer.render(st);
  panel.log('glasses UI up');
}

main().catch((e) => {
  document.body.insertAdjacentText('beforeend', `fatal: ${String(e)}`);
});
