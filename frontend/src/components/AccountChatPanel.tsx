import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AccountUser,
  AccountChatCandidate,
  AccountChatMessage,
  AccountChatSensing,
  ChatSessionSummary,
} from "../lib/api";
import {
  createChatSession,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessions,
  pickAccountChatCandidate,
  postQuickPhrase,
  sendAccountChatTurn,
  speakAacText,
} from "../lib/api";
import type { SensingState } from "../types";
import { usePartnerSpeech } from "../hooks/usePartnerSpeech";
import {
  IconMic,
  IconMicOff,
  IconSend,
  IconSpeaker,
} from "./Icons";

const CAPTURE_MS = 5000;
const CAPTURE_SAMPLE_MS = 100;

interface Props {
  user: AccountUser;
  backendReady: boolean;
  webcamEnabled?: boolean;
  pictureBoardOpen?: boolean;
  sensing?: SensingState;
  bindQuickPhrase?: (fn: ((text: string) => Promise<void>) | null) => void;
}

type PendingPick = {
  partnerText: string;
  candidates: AccountChatCandidate[];
};

function modeOf(values: Array<string | null | undefined>): string | null {
  const counts = new Map<string, number>();
  for (const v of values) {
    const key = (v || "").trim();
    if (!key || key.toLowerCase() === "none") continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let best: string | null = null;
  let bestN = 0;
  for (const [k, n] of counts) {
    if (n > bestN) {
      best = k;
      bestN = n;
    }
  }
  return best;
}

function aggregateCapture(samples: SensingState[]): AccountChatSensing {
  const emotions = samples.map((s) => s.affect);
  const gestures = samples.map((s) => s.gestureTag);
  const heads = samples.map((s) => s.headSignal);
  // Prefer the last detected head gesture in the window (momentary events).
  let head: string | null = null;
  for (let i = heads.length - 1; i >= 0; i--) {
    const h = heads[i];
    if (h) {
      head = h;
      break;
    }
  }
  return {
    emotion: modeOf(emotions),
    hand_gesture: modeOf(gestures),
    head_signal: head,
  };
}

export function AccountChatPanel({
  user,
  backendReady,
  webcamEnabled = false,
  pictureBoardOpen = false,
  sensing,
  bindQuickPhrase,
}: Props) {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionLimit, setSessionLimit] = useState(5);
  const [maxTurns, setMaxTurns] = useState(20);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [messages, setMessages] = useState<AccountChatMessage[]>([]);
  const [turnCount, setTurnCount] = useState(0);
  const [pending, setPending] = useState<PendingPick | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [captureLeftMs, setCaptureLeftMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sensingRef = useRef<SensingState | undefined>(sensing);
  sensingRef.current = sensing;
  const capturingRef = useRef(false);
  const liveQuickRef = useRef<string[]>([]);
  const captureDoneRef = useRef<(() => void) | null>(null);
  const pictureBoardOpenRef = useRef(pictureBoardOpen);
  pictureBoardOpenRef.current = pictureBoardOpen;
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [speakingIdx, setSpeakingIdx] = useState<number | null>(null);
  const [lastEmotion, setLastEmotion] = useState<string | null>(null);

  const speech = usePartnerSpeech((text) => {
    setInput((prev) => {
      const base = prev.trim();
      return base ? `${base} ${text}` : text;
    });
  });

  const displayName = `${user.first_name} ${user.last_name}`.trim();

  const applySessionDetail = useCallback((detail: Awaited<ReturnType<typeof fetchChatSession>>) => {
    setActiveId(detail.id);
    setTurnCount(detail.turn_count);
    const p = detail.pending;
    if (p && Array.isArray(p.candidates) && p.candidates.length > 0) {
      const partnerText = String(p.partner_text || "");
      const msgs = [...detail.messages];
      const last = msgs[msgs.length - 1];
      if (partnerText && !(last?.role === "partner" && last.text === partnerText)) {
        msgs.push({ role: "partner", text: partnerText });
      }
      setMessages(msgs);
      setPending({
        partnerText,
        candidates: p.candidates as AccountChatCandidate[],
      });
    } else {
      setMessages(detail.messages);
      setPending(null);
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    const data = await fetchChatSessions();
    setSessions(data.sessions);
    setSessionLimit(data.limit);
    setMaxTurns(data.max_turns);
    return data.sessions;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await refreshSessions();
        if (cancelled) return;
        if (list.length > 0) {
          const detail = await fetchChatSession(list[0].id);
          if (cancelled) return;
          applySessionDetail(detail);
        } else {
          setActiveId(null);
          setMessages([]);
          setTurnCount(0);
          setPending(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load sessions");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user.id, refreshSessions, applySessionDetail]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, pending, capturing, captureLeftMs]);

  useEffect(() => {
    if (!bindQuickPhrase) return;
    bindQuickPhrase(async (text: string) => {
      const phrase = text.trim();
      if (!phrase) return;
      if (!activeId) {
        setError("Open or start a conversation to log quick phrases.");
        return;
      }
      // During the post-partner wait with picture board on: collect the
      // phrase, show it, and end the wait early (skip generation).
      if (capturingRef.current && pictureBoardOpenRef.current) {
        liveQuickRef.current = [...liveQuickRef.current, phrase];
        setMessages((prev) => [
          ...prev,
          { role: "aac_user", text: phrase, kind: "quick" },
        ]);
        setError(null);
        captureDoneRef.current?.();
        return;
      }
      try {
        const message = await postQuickPhrase(activeId, phrase);
        setMessages((prev) => [...prev, message]);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not save quick phrase");
      }
    });
    return () => bindQuickPhrase(null);
  }, [activeId, bindQuickPhrase]);

  async function waitForTurnInput(): Promise<AccountChatSensing | null> {
    // Picture board on → wait up to 5s for a tap (early exit on phrase).
    // Webcam only → full 5s multimodal capture. Neither → no wait.
    if (!webcamEnabled && !pictureBoardOpen) return null;
    liveQuickRef.current = [];
    capturingRef.current = true;
    setCapturing(true);
    setCaptureLeftMs(CAPTURE_MS);
    const samples: SensingState[] = [];
    const started = Date.now();
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        captureDoneRef.current = null;
        resolve();
      };
      captureDoneRef.current = finish;
      const tick = () => {
        if (settled) return;
        const elapsed = Date.now() - started;
        const left = Math.max(0, CAPTURE_MS - elapsed);
        setCaptureLeftMs(left);
        if (webcamEnabled && sensingRef.current) {
          samples.push({ ...sensingRef.current });
        }
        // Phrase arrived → stop waiting (picture-board short-circuit).
        if (pictureBoardOpenRef.current && liveQuickRef.current.length > 0) {
          finish();
          return;
        }
        if (elapsed >= CAPTURE_MS) {
          finish();
          return;
        }
        window.setTimeout(tick, CAPTURE_SAMPLE_MS);
      };
      tick();
    });
    capturingRef.current = false;
    setCapturing(false);
    setCaptureLeftMs(0);
    // Picture-board reply skips generation; sensing not needed.
    if (liveQuickRef.current.length > 0) return null;
    if (!webcamEnabled) return null;
    const multimodal = aggregateCapture(samples);
    setLastEmotion(multimodal.emotion || null);
    return multimodal;
  }

  async function openSession(id: string) {
    setError(null);
    setBusy(true);
    try {
      const detail = await fetchChatSession(id);
      applySessionDetail(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open session");
    } finally {
      setBusy(false);
    }
  }

  async function handleNewSession() {
    setError(null);
    setBusy(true);
    try {
      const session = await createChatSession();
      await refreshSessions();
      setActiveId(session.id);
      setMessages([]);
      setTurnCount(0);
      setPending(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create session");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteSession(id: string) {
    setError(null);
    setBusy(true);
    try {
      await deleteChatSession(id);
      const list = await refreshSessions();
      if (activeId === id) {
        if (list[0]) {
          await openSession(list[0].id);
        } else {
          setActiveId(null);
          setMessages([]);
          setTurnCount(0);
          setPending(null);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete session");
    } finally {
      setBusy(false);
    }
  }

  async function handleSpeak(text: string, idx: number) {
    if (busy || speech.listening || speech.transcribing) return;
    setError(null);
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setSpeakingIdx(idx);
      const blob = await speakAacText(text, {
        voice: user.voice_preference || "Jason",
        emotion: webcamEnabled ? lastEmotion : null,
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setSpeakingIdx(null);
        audioRef.current = null;
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        setSpeakingIdx(null);
        setError("Could not play speech audio");
      };
      await audio.play();
    } catch (err) {
      setSpeakingIdx(null);
      setError(err instanceof Error ? err.message : "TTS failed");
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || !activeId || busy || !backendReady || pending) return;
    if (turnCount >= maxTurns) {
      setError(`This conversation reached the ${maxTurns}-turn limit.`);
      return;
    }
    speech.stop();
    setInput("");
    setError(null);
    setBusy(true);
    setMessages((prev) => [...prev, { role: "partner", text }]);
    try {
      const multimodal = await waitForTurnInput();
      const quickPhrases = [...liveQuickRef.current];
      liveQuickRef.current = [];

      // Picture board on + phrase within window → commit as dialogue turn,
      // skip the 4-option generation.
      if (pictureBoardOpen && quickPhrases.length > 0) {
        const result = await sendAccountChatTurn(
          activeId,
          text,
          null,
          quickPhrases,
        );
        setPending(null);
        setTurnCount(result.turn_count);
        setMessages((prev) => {
          // Replace optimistic quick bubble(s) with the committed turn reply.
          const withoutOptimistic = prev.filter(
            (m) =>
              !(
                m.role === "aac_user" &&
                m.kind === "quick" &&
                quickPhrases.includes(m.text)
              ),
          );
          return [
            ...withoutOptimistic,
            {
              role: "aac_user",
              text: result.aac_text || quickPhrases.join(" "),
              kind: "quick",
              turn_index: result.turn_index,
            },
          ];
        });
        setSessions((prev) =>
          prev.map((s) =>
            s.id === activeId
              ? {
                  ...s,
                  title: result.title || s.title,
                  turn_count: result.turn_count,
                }
              : s,
          ),
        );
        return;
      }

      const result = await sendAccountChatTurn(
        activeId,
        text,
        multimodal,
        null,
      );
      setPending({
        partnerText: result.partner_text,
        candidates: result.candidates,
      });
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeId
            ? { ...s, title: result.title || s.title }
            : s
        )
      );
    } catch (err) {
      setMessages((prev) => {
        let next = [...prev];
        while (
          next.length > 0 &&
          next[next.length - 1].role === "aac_user" &&
          next[next.length - 1].kind === "quick"
        ) {
          next = next.slice(0, -1);
        }
        const last = next[next.length - 1];
        if (last?.role === "partner" && last.text === text) {
          next = next.slice(0, -1);
        }
        return next;
      });
      setInput(text);
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      capturingRef.current = false;
      setCapturing(false);
      setCaptureLeftMs(0);
      setBusy(false);
    }
  }

  async function handlePick(candidateId: string) {
    if (!activeId || busy || !pending) return;
    setError(null);
    setBusy(true);
    try {
      const result = await pickAccountChatCandidate(activeId, candidateId);
      const speakIdx = messages.length;
      setPending(null);
      setMessages((prev) => [
        ...prev,
        {
          role: "aac_user",
          text: result.aac_text,
          turn_index: result.turn_index,
        },
      ]);
      setTurnCount(result.turn_count);
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeId ? { ...s, turn_count: result.turn_count } : s
        )
      );
      setBusy(false);
      await handleSpeak(result.aac_text, speakIdx);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select reply");
      setBusy(false);
    }
  }

  const atSessionCap = sessions.length >= sessionLimit;
  const atTurnCap = turnCount >= maxTurns;
  const awaitingPick = Boolean(pending);

  return (
    <div className={`account-chat${sessionsOpen ? "" : " sessions-collapsed"}`}>
      {sessionsOpen && (
        <aside className="account-chat-sessions" aria-label="Conversation history">
          <div className="account-chat-sessions-head">
            <h2>Sessions</h2>
            <span>
              {sessions.length}/{sessionLimit}
            </span>
          </div>
          <button
            type="button"
            className="account-chat-new"
            disabled={busy || atSessionCap || !backendReady}
            onClick={handleNewSession}
            title={
              atSessionCap
                ? `Delete a session first (max ${sessionLimit})`
                : "Start a new conversation"
            }
          >
            New conversation
          </button>
          <ul className="account-chat-session-list">
            {sessions.map((s) => (
              <li key={s.id} className={s.id === activeId ? "active" : ""}>
                <button
                  type="button"
                  className="account-chat-session-open"
                  disabled={busy}
                  onClick={() => openSession(s.id)}
                >
                  <strong>{s.title || "Conversation"}</strong>
                  <em>
                    {s.turn_count}/{s.max_turns} turns
                  </em>
                </button>
                <button
                  type="button"
                  className="account-chat-session-del"
                  disabled={busy}
                  onClick={() => handleDeleteSession(s.id)}
                  aria-label="Delete session"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
          {atSessionCap && (
            <p className="account-hint">
              Session limit reached. Delete an older conversation to start a new one.
            </p>
          )}
        </aside>
      )}

      <div className="chat-panel account-chat-panel">
        <div className="chat-header">
          <div className="chat-header-main">
            Speaking as {displayName}
            {activeId ? (
              <span className="account-chat-turn-meta">
                {" "}
                · turn {turnCount}/{maxTurns}
                {awaitingPick ? " · pick a reply" : ""}
              </span>
            ) : null}
          </div>
          <button
            type="button"
            className={`icon-text-btn${sessionsOpen ? " active" : ""}`}
            aria-pressed={sessionsOpen}
            onClick={() => setSessionsOpen((v) => !v)}
            title={sessionsOpen ? "Hide sessions" : "Sessions"}
          >
            {sessionsOpen ? "Hide sessions" : "Sessions"}
          </button>
        </div>

        <div className="chat-messages">
          {!activeId && (
            <p className="account-chat-empty">
              {sessions.length === 0
                ? "Start a new conversation to chat as this AAC user."
                : sessionsOpen
                  ? "Select a session from the left."
                  : "Open Sessions to select or start a conversation."}
            </p>
          )}
          {messages.map((msg, i) => {
            const isQuick = msg.kind === "quick";
            return (
              <div
                key={msg.id || `${msg.role}-${msg.kind || "msg"}-${i}`}
                className={`chat-bubble ${msg.role}${isQuick ? " quick" : ""}`}
              >
                <span className="chat-role">
                  {msg.role === "partner" ? "Partner" : displayName}
                  {isQuick ? <span className="badge badge-quick">quick</span> : null}
                </span>
                <div className={`chat-text${isQuick ? " chat-text-quick" : ""}`}>
                  {msg.text}
                </div>
                {msg.role === "aac_user" && msg.text && !isQuick && (
                  <button
                    type="button"
                    className="icon-btn tts-btn"
                    disabled={speakingIdx !== null}
                    onClick={() => handleSpeak(msg.text, i)}
                    title="Speak this reply"
                    aria-label="Speak this reply"
                  >
                    <IconSpeaker size={16} />
                  </button>
                )}
              </div>
            );
          })}

          {capturing && (
            <div className="chat-bubble aac_user capture-window">
              <span className="chat-role">
                {displayName}
                <span className="badge badge-capture">
                  {webcamEnabled && pictureBoardOpen
                    ? "input window"
                    : webcamEnabled
                      ? "webcam capture"
                      : "picture board"}
                </span>
              </span>
              <div className="chat-text capture-status">
                {webcamEnabled && pictureBoardOpen
                  ? "Tap a picture-board phrase to reply now, or wait for options…"
                  : webcamEnabled
                    ? "Capturing emotion, hand gesture, and head…"
                    : "Tap a picture-board phrase to reply now, or wait for options…"}
                <strong> {(captureLeftMs / 1000).toFixed(1)}s</strong>
                {webcamEnabled && sensing && (
                  <div className="capture-live">
                    <span>Emotion: {sensing.affect ?? "None"}</span>
                    <span>Hand: {sensing.gestureTag ?? "None"}</span>
                    <span>Head: {sensing.headSignal ?? "None"}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {busy && activeId && !pending && !capturing && (
            <div className="chat-bubble aac_user">
              <span className="chat-role">{displayName}</span>
              <div className="chat-text thinking">Composing 4 reply options…</div>
            </div>
          )}

          {pending && (
            <div className="chat-bubble aac_user picker">
              <span className="chat-role">
                {displayName}
                <span className="badge badge-picker">pick one (4 options)</span>
              </span>
              <div className="candidate-list">
                {pending.candidates.map((cand) => (
                  <button
                    key={cand.id}
                    type="button"
                    className="candidate-card"
                    disabled={busy}
                    onClick={() => handlePick(cand.id)}
                  >
                    <div className="candidate-strategy">{cand.label}</div>
                    <div className="candidate-text">{cand.text}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && <p className="error account-chat-error">{error}</p>}
        {speech.error && <p className="error account-chat-error">{speech.error}</p>}
        {speech.listening && (
          <p className="voice-status">Recording… click Stop when finished</p>
        )}
        {speech.transcribing && (
          <p className="voice-status">Transcribing with Whisper…</p>
        )}

        <form className="chat-input-row" onSubmit={handleSend}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              !activeId
                ? "Select or create a conversation first"
                : awaitingPick
                  ? "Choose a reply above before the partner continues"
                  : atTurnCap
                    ? "Turn limit reached, start a new conversation"
                    : speech.listening
                      ? "Recording…"
                      : speech.transcribing
                        ? "Transcribing…"
                        : "Partner message… (or use mic)"
            }
            disabled={
              !activeId ||
              busy ||
              !backendReady ||
              atTurnCap ||
              awaitingPick ||
              speech.transcribing
            }
            maxLength={4000}
          />
          {speech.supported && (
            <button
              type="button"
              className={`icon-btn mic-btn${speech.listening ? " listening" : ""}`}
              disabled={
                !activeId ||
                busy ||
                !backendReady ||
                atTurnCap ||
                awaitingPick ||
                speech.transcribing
              }
              onClick={() => speech.toggle()}
              title={speech.listening ? "Stop recording" : "Record partner message"}
              aria-label={speech.listening ? "Stop recording" : "Record partner message"}
              aria-pressed={speech.listening}
            >
              {speech.listening ? <IconMicOff size={18} /> : <IconMic size={18} />}
            </button>
          )}
          <button
            type="submit"
            className="icon-btn send-btn"
            title="Send"
            aria-label="Send"
            disabled={
              !activeId ||
              busy ||
              !backendReady ||
              atTurnCap ||
              awaitingPick ||
              speech.listening ||
              speech.transcribing ||
              !input.trim()
            }
          >
            <IconSend size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}
