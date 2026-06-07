import { useEffect, useRef, useState } from 'react';
import type { Lang } from '../i18n';

/* ────────────────────────────────────────────────────────────────────────
   Voice control via the Web Speech API (Chrome/Edge). Recognition language
   follows the UI language: en-US, or Cantonese (yue-Hant-HK) when set to 繁.

   Robustness: mic permission is primed via getUserMedia *before* starting
   recognition (so the first tap doesn't silently abort on the permission
   prompt), and recognition errors are surfaced as a short code instead of
   being swallowed — so the UI can tell the user *why* nothing happened.
   ──────────────────────────────────────────────────────────────────────── */

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onstart: (() => void) | null;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
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

/** Stable error codes the UI localizes; null when nothing is wrong. */
export type VoiceError = 'mic-blocked' | 'no-mic' | 'no-speech' | 'network' | 'start-failed' | null;

function mapError(code?: string): VoiceError {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed': return 'mic-blocked';
    case 'audio-capture': return 'no-mic';
    case 'no-speech': return 'no-speech';
    case 'network': return 'network';
    case 'aborted': return null; // normal when the user toggles off
    default: return code ? 'start-failed' : null;
  }
}

export interface Voice {
  supported: boolean;
  listening: boolean;
  /** Live partial transcript while the user is speaking. */
  interim: string;
  /** Last recognition error (mic blocked, no speech, …), or null. */
  error: VoiceError;
  start: () => void;
  stop: () => void;
  toggle: () => void;
}

export function useVoice(lang: Lang, onFinal: (text: string) => void): Voice {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<VoiceError>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const startingRef = useRef(false);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  const supported = typeof window !== 'undefined' && !!getRecognizer();

  const stop = () => { startingRef.current = false; recRef.current?.stop(); };

  const start = async () => {
    const SR = getRecognizer();
    if (!SR || recRef.current || startingRef.current) return;
    startingRef.current = true;
    setError(null);

    // Prime mic permission first — this is what makes the *first* tap work
    // (otherwise the permission prompt aborts the initial recognition).
    try {
      const md = navigator.mediaDevices;
      if (md?.getUserMedia) {
        const stream = await md.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
      }
    } catch {
      setError('mic-blocked');
      startingRef.current = false;
      return;
    }

    const rec = new SR();
    rec.lang = lang === 'zh-HK' ? 'yue-Hant-HK' : 'en-US';
    rec.interimResults = true;
    rec.continuous = false;
    rec.onstart = () => { setListening(true); setError(null); };
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
      startingRef.current = false;
      setListening(false);
      setInterim('');
    };
    rec.onerror = (e) => { setError(mapError(e?.error)); };

    recRef.current = rec;
    startingRef.current = false;
    try {
      rec.start();
    } catch {
      setError('start-failed');
      recRef.current = null;
      setListening(false);
    }
  };

  // Abort recognition on unmount.
  useEffect(() => () => recRef.current?.abort(), []);

  return {
    supported, listening, interim, error,
    start: () => { void start(); },
    stop,
    toggle: () => (listening || startingRef.current ? stop() : void start()),
  };
}
