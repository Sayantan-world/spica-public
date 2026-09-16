import { useEffect, useRef, useState } from "react";
import type { AccountStored, AccountUpload, AccountUser, VoiceOption } from "../lib/api";
import {
  deleteAccountUpload,
  fetchAccountMe,
  fetchAccountStored,
  fetchAccountUploads,
  fetchVoiceOptions,
  loginAccount,
  processAccountUploadStream,
  registerAccount,
  setVoicePreference,
  fetchVoiceSampleClip,
  uploadAccountText,
  uploadAccountTxt,
} from "../lib/api";
import {
  IconCheck,
  IconDatabase,
  IconEye,
  IconGrid,
  IconVoice,
  IconX,
} from "./Icons";

type Mode = "closed" | "register" | "login";

interface Props {
  onUserChange?: (user: AccountUser | null) => void;
  variant?: "sidebar" | "landing";
  pictureBoardOpen?: boolean;
  onPictureBoardToggle?: () => void;
}

export function AccountNav({
  onUserChange,
  variant = "sidebar",
  pictureBoardOpen = false,
  onPictureBoardToggle,
}: Props) {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [mode, setMode] = useState<Mode>("closed");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const [uploads, setUploads] = useState<AccountUpload[]>([]);
  const [limit, setLimit] = useState(5);
  const [maxChars, setMaxChars] = useState(10000);
  const [feed, setFeed] = useState<"txt" | "paste">("txt");
  const [pasteName, setPasteName] = useState("notes.txt");
  const [pasteBody, setPasteBody] = useState("");
  const [processMsg, setProcessMsg] = useState<string | null>(null);
  const [progressById, setProgressById] = useState<
    Record<string, { pct: number; message: string }>
  >({});
  const [storedOpen, setStoredOpen] = useState(false);
  const [stored, setStored] = useState<AccountStored | null>(null);
  const [storedBusy, setStoredBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAccountMe()
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        onUserChange?.(u);
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        onUserChange?.(null);
      });
    return () => {
      cancelled = true;
    };
    // intentionally mount-only; parent notifies via setUserAndNotify afterward
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setUserAndNotify(next: AccountUser | null) {
    setUser(next);
    onUserChange?.(next);
  }

  useEffect(() => {
    if (!user) {
      setUploads([]);
      setDataOpen(false);
      setStoredOpen(false);
      setStored(null);
      return;
    }
    fetchAccountUploads()
      .then((data) => {
        setUploads(data.uploads);
        setLimit(data.limit);
        setMaxChars(data.max_chars);
      })
      .catch((e: Error) => setError(e.message));
  }, [user]);

  async function handleRegister(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const next = await registerAccount({
        username: String(form.get("username") ?? ""),
        first_name: String(form.get("first_name") ?? ""),
        last_name: String(form.get("last_name") ?? ""),
        dob: String(form.get("dob") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      setUserAndNotify(next);
      setMode("closed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add user");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogin(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const next = await loginAccount({
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      setUserAndNotify(next);
      setMode("closed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not log in");
    } finally {
      setBusy(false);
    }
  }

  async function handlePickVoice(voiceId: string) {
    if (!user || busy) return;
    setError(null);
    setPreviewingVoice(voiceId);
    try {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current = null;
      }
      const selected =
        (user.voice_preference || "Jason").toLowerCase() === voiceId.toLowerCase();
      if (!selected) {
        const next = await setVoicePreference(voiceId);
        setUserAndNotify(next);
      }
      const blob = await fetchVoiceSampleClip(voiceId);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      previewAudioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setPreviewingVoice(null);
        previewAudioRef.current = null;
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        setPreviewingVoice(null);
        setError("Could not play sample voice");
      };
      await audio.play();
    } catch (e) {
      setPreviewingVoice(null);
      setError(e instanceof Error ? e.message : "Voice preview failed");
    }
  }

  async function refreshUploads() {
    const data = await fetchAccountUploads();
    setUploads(data.uploads);
    setLimit(data.limit);
    setMaxChars(data.max_chars);
  }

  async function handleTxt(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await uploadAccountTxt(file);
      await refreshUploads();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function handlePaste(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await uploadAccountText({ filename: pasteName, content: pasteBody });
      setPasteBody("");
      await refreshUploads();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteAccountUpload(id);
      await refreshUploads();
      if (storedOpen) {
        const next = await fetchAccountStored();
        setStored(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function openStored() {
    setStoredBusy(true);
    setError(null);
    try {
      const data = await fetchAccountStored();
      setStored(data);
      setStoredOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load stored data");
    } finally {
      setStoredBusy(false);
    }
  }

  async function handleProcess(id: string) {
    setBusy(true);
    setError(null);
    setProcessMsg(null);
    setProgressById((prev) => ({
      ...prev,
      [id]: { pct: 1, message: "Starting…" },
    }));
    setUploads((prev) =>
      prev.map((u) =>
        u.id === id ? { ...u, process_status: "processing", process_progress: 1 } : u
      )
    );
    try {
      let summary: string | null = null;
      await processAccountUploadStream(id, (evt) => {
        if (evt.type === "progress") {
          setProgressById((prev) => ({
            ...prev,
            [id]: { pct: evt.pct, message: evt.message },
          }));
          setUploads((prev) =>
            prev.map((u) =>
              u.id === id
                ? {
                    ...u,
                    process_status: "processing",
                    process_progress: evt.pct,
                    process_message: evt.message,
                  }
                : u
            )
          );
        } else if (evt.type === "complete") {
          summary = "Processed";
          setProgressById((prev) => ({
            ...prev,
            [id]: { pct: 100, message: "Done" },
          }));
        }
      });
      await refreshUploads();
      const me = await fetchAccountMe();
      if (me) setUserAndNotify(me);
      setProcessMsg(summary);
      window.setTimeout(() => {
        setProgressById((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }, 1200);
    } catch (err) {
      setProgressById((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setError(err instanceof Error ? err.message : "Process failed");
      await refreshUploads().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  const profileFactEntries = Object.entries(stored?.profile_facts ?? {});
  const hasStoredContent =
    (stored?.facts.length ?? 0) > 0 ||
    (stored?.relations.length ?? 0) > 0 ||
    (stored?.chunks.length ?? 0) > 0 ||
    profileFactEntries.length > 0;

  return (
    <div className={`account-block ${variant === "landing" ? "account-block-landing" : ""}`}>
      <nav className="account-nav" aria-label="Account">
        {user ? (
          <>
            <span className="account-nav-name">
              {user.first_name} {user.last_name}
              {user.username ? (
                <em className="account-nav-uname"> @{user.username}</em>
              ) : null}
            </span>
            <button
              type="button"
              className={`icon-text-btn${dataOpen ? " active" : ""}`}
              onClick={() => {
                setDataOpen((v) => !v);
                setVoiceOpen(false);
              }}
            >
              <IconDatabase size={16} />
              <span>{dataOpen ? "Hide data" : "Data"}</span>
            </button>
            <button
              type="button"
              className={`icon-text-btn${voiceOpen ? " active" : ""}`}
              title={voiceOpen ? "Hide voice" : "Voice"}
              aria-label={voiceOpen ? "Hide voice" : "Voice"}
              onClick={async () => {
                const next = !voiceOpen;
                setVoiceOpen(next);
                setDataOpen(false);
                if (next && voiceOptions.length === 0) {
                  try {
                    const data = await fetchVoiceOptions();
                    setVoiceOptions(data.options);
                    if (data.voice) {
                      setUserAndNotify({
                        ...(user as AccountUser),
                        voice_preference: data.voice,
                      });
                    }
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Could not load voices");
                  }
                }
              }}
            >
              <IconVoice size={16} />
              <span>{voiceOpen ? "Hide voice" : "Voice"}</span>
            </button>
            {variant === "sidebar" && onPictureBoardToggle && (
              <button
                type="button"
                className={`icon-text-btn${pictureBoardOpen ? " active" : ""}`}
                title={pictureBoardOpen ? "Hide pictureboard" : "Pictureboard"}
                aria-label={pictureBoardOpen ? "Hide pictureboard" : "Pictureboard"}
                aria-pressed={pictureBoardOpen}
                onClick={onPictureBoardToggle}
              >
                <IconGrid size={16} />
                <span>{pictureBoardOpen ? "Hide" : "Pictureboard"}</span>
              </button>
            )}
          </>
        ) : (
          <>
            <button
              type="button"
              className={variant === "landing" ? "landing-cta landing-cta-primary" : undefined}
              onClick={() => { setMode("login"); setError(null); }}
            >
              Log in
            </button>
            <button
              type="button"
              className={variant === "landing" ? "landing-cta" : undefined}
              onClick={() => { setMode("register"); setError(null); }}
            >
              Explore SPICA
            </button>
          </>
        )}
      </nav>

      {user && dataOpen && (
        <div className="account-data">
          <div className="account-data-header">
            <p className="account-data-label">Data ({uploads.length}/{limit})</p>
            <button
              type="button"
              className="icon-btn"
              disabled={storedBusy || busy}
              onClick={openStored}
              title={storedBusy ? "Loading stored data…" : "View stored"}
              aria-label={storedBusy ? "Loading stored data" : "View stored"}
            >
              <IconEye size={16} />
            </button>
          </div>
          <div className="account-feed-choice">
            <button
              type="button"
              className={feed === "txt" ? "active" : ""}
              onClick={() => setFeed("txt")}
            >
              Raw text (.txt)
            </button>
            <button
              type="button"
              className={feed === "paste" ? "active" : ""}
              onClick={() => setFeed("paste")}
            >
              Paste text
            </button>
          </div>

          {feed === "txt" ? (
            <div className="account-feed-panel">
              <input
                ref={fileRef}
                type="file"
                accept=".txt,text/plain"
                hidden
                onChange={handleTxt}
              />
              <button
                type="button"
                disabled={busy || uploads.length >= limit}
                onClick={() => fileRef.current?.click()}
              >
                Choose .txt file
              </button>
              <p className="account-hint">
                Up to {maxChars.toLocaleString()} characters per file. JSON or plain text.
                Use Process text after upload.
              </p>
            </div>
          ) : (
            <form className="account-feed-panel" onSubmit={handlePaste}>
              <input
                type="text"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
                placeholder="notes.txt"
                maxLength={120}
              />
              <textarea
                value={pasteBody}
                onChange={(e) => setPasteBody(e.target.value)}
                maxLength={maxChars}
                rows={5}
                placeholder="Paste or type notes"
                required
              />
              <div className="account-char-row">
                <span>
                  {pasteBody.length}/{maxChars}
                </span>
                <button type="submit" disabled={busy || uploads.length >= limit || !pasteBody.trim()}>
                  Save text
                </button>
              </div>
            </form>
          )}

          {uploads.length > 0 && (
            <ul className="account-file-list">
              {uploads.map((item) => {
                const live = progressById[item.id];
                const pct = live?.pct ?? item.process_progress ?? 0;
                const msg =
                  live?.message ||
                  item.process_message ||
                  (item.process_status === "processing" ? "Processing…" : "");
                const showBar =
                  Boolean(live) || item.process_status === "processing";
                const isDone = item.process_status === "done";
                const emptyDone = isDone && !(item.chunk_count && item.chunk_count > 0);
                const canProcess =
                  item.process_status !== "processing" && (!isDone || emptyDone);
                const processDisabled = busy || !canProcess;
                return (
                  <li key={item.id}>
                    <div className="account-file-row">
                      <span>
                        {item.filename}
                        <em>
                          {item.char_count} chars
                          {item.process_status ? ` · ${item.process_status}` : ""}
                          {isDone && item.chunk_count
                            ? ` · ${item.chunk_count} chunks`
                            : ""}
                          {emptyDone ? " · no data stored" : ""}
                        </em>
                      </span>
                      <span className="account-file-actions">
                        {canProcess ? (
                          <button
                            type="button"
                            disabled={processDisabled}
                            onClick={() => handleProcess(item.id)}
                          >
                            {emptyDone ? "Re-process" : "Process text"}
                          </button>
                        ) : isDone ? null : (
                          <button type="button" disabled>
                            Process text
                          </button>
                        )}
                        <button type="button" disabled={busy} onClick={() => handleDelete(item.id)}>
                          Delete
                        </button>
                      </span>
                    </div>
                    {showBar && (
                      <div className="account-progress" aria-live="polite">
                        <div className="account-progress-meta">
                          <span>{msg}</span>
                          <span>{Math.round(pct)}%</span>
                        </div>
                        <div className="account-progress-track">
                          <div
                            className="account-progress-fill"
                            style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {processMsg && <p className="account-hint">{processMsg}</p>}
        </div>
      )}

      {user && voiceOpen && (
        <div className="account-data account-voice">
          <p className="account-data-label">
            Voice · {user.voice_preference || "Jason"}
          </p>
          {(["male", "female"] as const).map((gender) => (
            <div key={gender} className="account-voice-group">
              <h3>{gender === "male" ? "Male" : "Female"}</h3>
              <div className="account-voice-chips">
                {voiceOptions
                  .filter((v) => v.gender === gender)
                  .map((v) => {
                    const selected =
                      (user.voice_preference || "Jason").toLowerCase() ===
                      v.id.toLowerCase();
                    const playing = previewingVoice === v.id;
                    return (
                      <button
                        key={v.id}
                        type="button"
                        className={`voice-chip${selected ? " selected" : ""}${playing ? " playing" : ""}`}
                        disabled={busy || (previewingVoice !== null && !playing)}
                        title={`${v.label}, play sample & select`}
                        aria-pressed={selected}
                        onClick={() => handlePickVoice(v.id)}
                      >
                        <span className="voice-chip-name">{v.label}</span>
                        {selected && (
                          <span className="voice-chip-icon" aria-hidden="true">
                            <IconCheck size={15} className="voice-check" />
                          </span>
                        )}
                      </button>
                    );
                  })}
              </div>
            </div>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {storedOpen && (
        <div
          className="account-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="stored-title"
        >
          <div className="account-card account-stored-card">
            <div className="account-stored-header">
              <h2 id="stored-title">Stored for you</h2>
              <button
                type="button"
                className="icon-btn account-stored-close"
                onClick={() => setStoredOpen(false)}
                title="Close"
                aria-label="Close"
              >
                <IconX size={16} />
              </button>
            </div>
            {!hasStoredContent ? (
              <p className="account-hint">Nothing stored yet. Process a text file first.</p>
            ) : (
              <div className="account-stored-body">
                {(stored?.facts.length ?? 0) > 0 && (
                  <section>
                    <h3>Facts ({stored!.facts.length})</h3>
                    <ul className="account-stored-list">
                      {stored!.facts.map((f, i) => (
                        <li key={`fact-${i}`}>
                          <p>{f.text}</p>
                          {typeof f.char_count === "number" && (
                            <em>{f.char_count} chars</em>
                          )}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {(stored?.chunks.length ?? 0) > 0 && (
                  <section>
                    <h3>Memory chunks ({stored!.chunks.length})</h3>
                    <ul className="account-stored-list">
                      {stored!.chunks.map((c) => (
                        <li key={c.id}>
                          <p>{c.text}</p>
                          <em>
                            {c.bucket}
                            {c.source_kind ? ` · ${c.source_kind}` : ""}
                          </em>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {(stored?.relations.length ?? 0) > 0 && (
                  <section>
                    <h3>Relations ({stored!.relations.length})</h3>
                    <ul className="account-stored-list">
                      {stored!.relations.map((r, i) => (
                        <li key={`rel-${i}`}>
                          <p>
                            {[r.subject, r.relation, r.object].filter(Boolean).join(", ")}
                          </p>
                          {r.note ? <em>{r.note}</em> : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {profileFactEntries.length > 0 && (
                  <section>
                    <h3>Profile facts</h3>
                    <ul className="account-stored-list">
                      {profileFactEntries.map(([k, v]) => (
                        <li key={k}>
                          <p>
                            <strong>{k}</strong>: {v}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {mode !== "closed" && (
        <div className="account-modal" role="dialog" aria-modal="true">
          <form
            className="account-card"
            onSubmit={mode === "register" ? handleRegister : handleLogin}
          >
            <h2>{mode === "register" ? "Create account" : "Log in"}</h2>
            <label>
              Username
              <input
                name="username"
                type="text"
                autoComplete="username"
                required
                minLength={3}
                maxLength={40}
                pattern="[A-Za-z0-9_]+"
                title="3-40 characters: letters, numbers, underscore"
              />
            </label>
            {mode === "register" && (
              <>
                <label>
                  First name
                  <input name="first_name" type="text" autoComplete="given-name" required />
                </label>
                <label>
                  Last name
                  <input name="last_name" type="text" autoComplete="family-name" required />
                </label>
                <label>
                  Date of birth
                  <input name="dob" type="date" required max={new Date().toISOString().slice(0, 10)} />
                </label>
              </>
            )}
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                minLength={mode === "register" ? 8 : 1}
                required
              />
            </label>
            {error && <p className="error">{error}</p>}
            <div className="account-card-actions">
              <button type="button" onClick={() => { setMode("closed"); setError(null); }}>
                Cancel
              </button>
              <button type="submit" disabled={busy}>
                {mode === "register" ? "Create account" : "Log in"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
