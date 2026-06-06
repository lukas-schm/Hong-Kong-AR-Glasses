import { useEffect, useRef, useState } from 'react';
import type { Lang } from '../i18n';

/* ────────────────────────────────────────────────────────────────────────
   Voice control via the Web Speech API (Chrome/Edge/Safari). Recognition
   language follows the UI language: en-US, or Cantonese (yue-Hant-HK)
   when the UI is set to 繁. Degrades gracefully when unsupported.
   ──────────────────────────────────────────────────────────────────────── */

// Minimal structural typing — lib.dom has no SpeechRecognition types.
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}

type SRConstructor = new () => SpeechRecognitionLike;

function getRecognizer(): SRConstructor | undefined {
  const w = window as unknown as { SpeechRecognition?: SRConstructor; webkitSpeechRecognition?: SRConstructor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export interface Voice {
  supported: boolean;
  listening: boolean;
  /** Live partial transcript while the user is speaking. */
  interim: string;
  start: () => void;
  stop: () => void;
  toggle: () => void;
}

export function useVoice(lang: Lang, onFinal: (text: string) => void): Voice {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  const supported = typeof window !== 'undefined' && !!getRecognizer();

  const stop = () => recRef.current?.stop();

  const start = () => {
    const SR = getRecognizer();
    if (!SR || recRef.current) return;
    const rec = new SR();
    rec.lang = lang === 'zh-HK' ? 'yue-Hant-HK' : 'en-US';
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (e) => {
      let interimText = '';
      let finalText = '';
      for (let i = 0; i < e.results.length; i += 1) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interimText += r[0].transcript;
      }
      setInterim(interimText);
      if (finalText.trim()) {
        setInterim('');
        onFinalRef.current(finalText.trim());
      }
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      setInterim('');
    };
    rec.onerror = () => {
      setListening(false);
    };
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  // Abort recognition on unmount.
  useEffect(() => () => recRef.current?.abort(), []);

  return { supported, listening, interim, start, stop, toggle: () => (listening ? stop() : start()) };
}
