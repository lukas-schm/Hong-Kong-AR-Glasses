import { useEffect, useRef, useState } from 'react';
import type { HKPatient } from '../../data/hkPatients';
import type { ArmPredictions } from '../../utils/prediction';
import { runAssistant, type AssistantAction } from '../../utils/assistant';
import { useLang } from '../../i18n';

/* ────────────────────────────────────────────────────────────────────────
   Chat surface over the shared assistant engine — same intents as voice:
   open patients by name, query vitals, simulate interventions (scored
   against the trained causal model), mortality overview.
   ──────────────────────────────────────────────────────────────────────── */

interface ChatMsg {
  role: 'user' | 'bot';
  text: string;
}

interface ChatBotProps {
  patient: HKPatient;
  basePredictions: ArmPredictions | null;
  onAction?: (action: AssistantAction) => void;
}

export function ChatBot({ patient, basePredictions, onAction }: ChatBotProps) {
  const { t } = useLang();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  // Aborts in-flight scenario scoring when the patient changes or we unmount,
  // so a late reply can never land in another patient's conversation.
  const abortRef = useRef<AbortController | null>(null);

  // Reset conversation when the patient changes.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setMessages([{ role: 'bot', text: t('chatGreeting') }]);
    setBusy(false);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient.hkid]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    const signal = abortRef.current?.signal;
    if (!signal) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text }]);
    setBusy(true);
    try {
      const reply = await runAssistant(text, { patient, basePredictions }, signal);
      if (!signal.aborted) {
        setMessages((m) => [...m, { role: 'bot', text: reply.text }]);
        if (reply.action) onAction?.(reply.action);
      }
    } catch {
      /* aborted — patient changed mid-request */
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  return (
    <section className="hkehr-card hkehr-chat">
      <h2>{t('chatTitle')}</h2>
      <div className="hkehr-chat__log" ref={logRef}>
        {messages.map((m, i) => (
          <div key={i} className={`hkehr-msg hkehr-msg--${m.role}`}>{m.text}</div>
        ))}
        {busy && <div className="hkehr-msg hkehr-msg--bot hkehr-msg--busy">{t('chatThinking')}</div>}
      </div>
      <div className="hkehr-chat__input">
        <input
          value={input}
          placeholder={t('chatPlaceholder')}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send(input)}
          disabled={busy}
        />
        <button className="hkehr-btn hkehr-btn--primary" onClick={() => send(input)} disabled={busy || !input.trim()}>
          {t('send')}
        </button>
      </div>
    </section>
  );
}
