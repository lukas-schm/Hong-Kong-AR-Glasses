/* ────────────────────────────────────────────────────────────────────────
   G2 microphone capture.

   The Even App's WebView has no Web Speech API path to the glasses' 4-mic
   array; instead the SDK streams raw 16 kHz mono 16-bit PCM through
   audioEvent pushes after audioControl(true). We buffer the PCM while
   listening, wrap it into a WAV on stop, and POST it to the CDARS server
   for transcription (api/agent/asr.py · faster-whisper). The transcript
   then runs through the normal /api/v1/agent/command path.
   ──────────────────────────────────────────────────────────────────────── */
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk';
import { SERVER } from './config';

const SAMPLE_RATE = 16000;

function pcmToWav(chunks: Uint8Array[]): Blob {
  const dataLen = chunks.reduce((n, c) => n + c.length, 0);
  const buf = new ArrayBuffer(44 + dataLen);
  const v = new DataView(buf);
  const str = (off: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + dataLen, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, SAMPLE_RATE, true); v.setUint32(28, SAMPLE_RATE * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, dataLen, true);
  let off = 44;
  const out = new Uint8Array(buf);
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return new Blob([buf], { type: 'audio/wav' });
}

export class G2Voice {
  listening = false;
  private chunks: Uint8Array[] = [];

  constructor(private bridge: EvenAppBridge, private lang: 'en' | 'zh-HK' = 'en') {}

  /** Feed audioEvent pushes from the single onEvenHubEvent listener. */
  onAudio(pcm: Uint8Array) {
    if (this.listening) this.chunks.push(pcm);
  }

  async start(): Promise<boolean> {
    if (this.listening) return true;
    this.chunks = [];
    const ok = await this.bridge.audioControl(true);
    this.listening = ok;
    return ok;
  }

  /**
   * Stop capture and ask Gemini about the open patient (transcription +
   * reasoning + Google Search grounding happen server-side in one call).
   * Returns the answer text to show in the glasses text window.
   */
  async stopAndAsk(patientKey: string): Promise<string | null> {
    if (!this.listening) return null;
    this.listening = false;
    await this.bridge.audioControl(false).catch(() => {});
    if (!this.chunks.length) return 'No audio captured — tap and speak.';
    const wav = pcmToWav(this.chunks);
    this.chunks = [];
    try {
      const res = await fetch(
        `${SERVER}/api/v1/agent/ask?patient=${encodeURIComponent(patientKey)}&lang=${this.lang}`,
        { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav },
      );
      if (!res.ok) {
        if (res.status === 503) return 'Voice off — GEMINI_API_KEY not set on the server.';
        return `Voice error (${res.status}).`;
      }
      const { answer } = (await res.json()) as { answer?: string };
      return answer?.trim() || 'No answer.';
    } catch {
      return 'CDARS server unreachable.';
    }
  }
}
