import { useCallback, useEffect, useRef, useState } from "react";
import { transcribePartnerAudio } from "../lib/api";

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const n = samples.length;
  const buffer = new ArrayBuffer(44 + n * 2);
  const view = new DataView(buffer);

  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + n * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, n * 2, true);

  let offset = 44;
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function usePartnerSpeech(onTranscript: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const chunksRef = useRef<Float32Array[]>([]);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  useEffect(() => {
    setSupported(
      typeof window !== "undefined" &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof AudioContext !== "undefined",
    );
  }, []);

  const cleanup = useCallback(() => {
    try {
      processorRef.current?.disconnect();
    } catch {
      // ignore
    }
    processorRef.current = null;
    try {
      ctxRef.current?.close();
    } catch {
      // ignore
    }
    ctxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const stop = useCallback(async () => {
    if (!listening) return;
    setListening(false);

    const sampleRate = ctxRef.current?.sampleRate || 16000;
    const pieces = chunksRef.current;
    cleanup();

    if (pieces.length === 0) {
      setError("No audio captured, try again");
      return;
    }
    let total = 0;
    for (const p of pieces) total += p.length;
    const merged = new Float32Array(total);
    let offset = 0;
    for (const p of pieces) {
      merged.set(p, offset);
      offset += p.length;
    }
    // Downsample to 16 kHz for Whisper if needed.
    const targetRate = 16000;
    let pcm = merged;
    if (Math.abs(sampleRate - targetRate) > 1) {
      const ratio = sampleRate / targetRate;
      const outLen = Math.max(1, Math.floor(merged.length / ratio));
      const out = new Float32Array(outLen);
      for (let i = 0; i < outLen; i++) {
        out[i] = merged[Math.min(merged.length - 1, Math.floor(i * ratio))] ?? 0;
      }
      pcm = out;
    }
    const blob = encodeWav(pcm, targetRate);
    if (blob.size < 1000) {
      setError("Recording too short, try again");
      return;
    }

    setTranscribing(true);
    setError(null);
    try {
      const result = await transcribePartnerAudio(blob);
      const text = (result.text || "").trim();
      if (!text) throw new Error("Empty transcript");
      onTranscriptRef.current(text);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transcription failed");
    } finally {
      setTranscribing(false);
    }
  }, [cleanup, listening]);

  const start = useCallback(async () => {
    setError(null);
    if (listening || transcribing) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      // ScriptProcessor is deprecated but widely supported; size 4096 is fine for speech.
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        chunksRef.current.push(new Float32Array(input));
      };
      source.connect(processor);
      // Keep processor alive without playing mic through speakers.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      processor.connect(mute);
      mute.connect(ctx.destination);
      setListening(true);
    } catch (e) {
      setError(
        e instanceof Error && /Permission|NotAllowed/i.test(e.message)
          ? "Microphone permission denied."
          : e instanceof Error
            ? e.message
            : "Could not open microphone",
      );
      cleanup();
      setListening(false);
    }
  }, [cleanup, listening, transcribing]);

  const toggle = useCallback(async () => {
    if (listening) await stop();
    else await start();
  }, [listening, start, stop]);

  useEffect(() => () => cleanup(), [cleanup]);

  return { supported, listening, transcribing, error, start, stop, toggle };
}
