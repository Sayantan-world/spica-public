const API_BASE = "";

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return false;
    const data = await res.json();
    return data.models_ready === true;
  } catch {
    return false;
  }
}

const ACCOUNT_TOKEN_KEY = "spica_account_token";

export type AccountUser = {
  id: string;
  username?: string;
  first_name: string;
  last_name: string;
  dob: string;
  voice_preference?: string;
  relations?: Array<{
    subject?: string;
    relation?: string;
    object?: string;
    note?: string;
  }>;
  profile_facts?: Record<string, string>;
  facts?: Array<{
    text: string;
    char_count?: number;
    source_upload_id?: string | null;
  }>;
};

export type AccountStored = {
  facts: Array<{
    text: string;
    char_count?: number;
    source_upload_id?: string | null;
  }>;
  relations: Array<{
    subject?: string;
    relation?: string;
    object?: string;
    note?: string;
  }>;
  profile_facts: Record<string, string>;
  chunks: Array<{
    id: string;
    upload_id?: string | null;
    text: string;
    bucket: string;
    source_kind?: string | null;
    created_at?: string | null;
  }>;
};

export type AccountUpload = {
  id: string;
  kind: "txt_file" | "pasted_text" | string;
  filename: string;
  char_count: number;
  content_type?: string | null;
  process_status?: "pending" | "processing" | "done" | "failed" | string;
  process_progress?: number;
  process_message?: string;
  chunk_count?: number;
  processed_at?: string | null;
  created_at: string | null;
};

function accountToken(): string | null {
  return localStorage.getItem(ACCOUNT_TOKEN_KEY);
}

export function setAccountToken(token: string | null) {
  if (token) localStorage.setItem(ACCOUNT_TOKEN_KEY, token);
  else localStorage.removeItem(ACCOUNT_TOKEN_KEY);
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = accountToken();
  return {
    ...(extra ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function accountError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((d: { msg?: string }) => d.msg || JSON.stringify(d))
        .join("; ");
    }
  } catch {
    // ignore
  }
  return `API error: ${res.status}`;
}

export async function registerAccount(body: {
  username: string;
  first_name: string;
  last_name: string;
  dob: string;
  password: string;
}): Promise<AccountUser> {
  const res = await fetch(`${API_BASE}/account/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  setAccountToken(data.token);
  return data.user as AccountUser;
}

export async function loginAccount(body: {
  username: string;
  password: string;
}): Promise<AccountUser> {
  const res = await fetch(`${API_BASE}/account/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  setAccountToken(data.token);
  return data.user as AccountUser;
}

export async function logoutAccount(): Promise<void> {
  try {
    await fetch(`${API_BASE}/account/logout`, {
      method: "POST",
      headers: authHeaders(),
    });
  } finally {
    setAccountToken(null);
  }
}

export async function fetchAccountMe(): Promise<AccountUser | null> {
  if (!accountToken()) return null;
  const res = await fetch(`${API_BASE}/account/me`, { headers: authHeaders() });
  if (res.status === 401) {
    setAccountToken(null);
    return null;
  }
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  return data.user as AccountUser;
}

export async function fetchAccountStored(): Promise<AccountStored> {
  const res = await fetch(`${API_BASE}/account/stored`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await accountError(res));
  return (await res.json()) as AccountStored;
}

export async function fetchAccountUploads(): Promise<{
  uploads: AccountUpload[];
  limit: number;
  max_chars: number;
}> {
  const res = await fetch(`${API_BASE}/account/uploads`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function uploadAccountTxt(file: File): Promise<AccountUpload> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/account/uploads/txt`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function uploadAccountText(body: {
  filename?: string;
  content: string;
}): Promise<AccountUpload> {
  const res = await fetch(`${API_BASE}/account/uploads/text`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function deleteAccountUpload(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/account/uploads/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await accountError(res));
}

export async function processAccountUpload(id: string): Promise<{
  upload: AccountUpload;
  content_type: string;
  chunks_stored: number;
  relations_added: number;
  relations_total: number;
  profile_facts: Record<string, string>;
}> {
  const res = await fetch(
    `${API_BASE}/account/uploads/${encodeURIComponent(id)}/process`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export type ProcessProgressEvent =
  | { type: "progress"; pct: number; message: string }
  | {
      type: "complete";
      result: {
        upload: AccountUpload;
        content_type: string;
        chunks_stored: number;
        relations_added: number;
        relations_total: number;
        profile_facts: Record<string, string>;
      };
    }
  | { type: "error"; message: string; pct?: number };

export async function processAccountUploadStream(
  id: string,
  onEvent: (evt: ProcessProgressEvent) => void,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/account/uploads/${encodeURIComponent(id)}/process/stream`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
  if (!res.body) throw new Error("no response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalError: string | null = null;
  let completed = false;

  const emitFrame = (frame: string) => {
    const line = frame.split("\n").find((l) => l.startsWith("data:"));
    if (!line) return;
    const json = line.slice(5).trim();
    if (!json) return;
    try {
      const evt = JSON.parse(json) as ProcessProgressEvent;
      onEvent(evt);
      if (evt.type === "complete") completed = true;
      if (evt.type === "error") finalError = evt.message;
    } catch (e) {
      console.warn("process SSE parse failed", e, json.slice(0, 200));
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const frame of parts) emitFrame(frame);
  }
  if (buffer.trim()) emitFrame(buffer);

  if (finalError) throw new Error(finalError);
  if (!completed) throw new Error("processing ended without completion");
}


export type ChatSessionSummary = {
  id: string;
  title: string;
  turn_count: number;
  max_turns: number;
  created_at: string | null;
  updated_at: string | null;
};

export type AccountChatMessage = {
  role: "partner" | "aac_user";
  text: string;
  turn_index?: number;
  kind?: "quick" | string;
  id?: string;
};

export type AccountChatCandidate = {
  id: string;
  strategy: string;
  label: string;
  text: string;
};

export async function fetchChatSessions(): Promise<{
  sessions: ChatSessionSummary[];
  limit: number;
  max_turns: number;
}> {
  const res = await fetch(`${API_BASE}/account/chat/sessions`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function createChatSession(title?: string): Promise<ChatSessionSummary> {
  const res = await fetch(`${API_BASE}/account/chat/sessions`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ title: title ?? null }),
  });
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  return data.session as ChatSessionSummary;
}

export async function fetchChatSession(id: string): Promise<{
  id: string;
  title: string;
  turn_count: number;
  max_turns: number;
  profile_summary: string;
  messages: AccountChatMessage[];
  pending?: {
    partner_text?: string;
    candidates?: AccountChatCandidate[];
  } | null;
}> {
  const res = await fetch(
    `${API_BASE}/account/chat/sessions/${encodeURIComponent(id)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  return data.session;
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/account/chat/sessions/${encodeURIComponent(id)}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
}

export type AccountChatSensing = {
  emotion?: string | null;
  hand_gesture?: string | null;
  head_signal?: string | null;
};

export async function sendAccountChatTurn(
  sessionId: string,
  text: string,
  sensing?: AccountChatSensing | null,
  quickPhrases?: string[] | null,
): Promise<{
  partner_text: string;
  candidates: AccountChatCandidate[];
  turn_count: number;
  max_turns: number;
  awaiting_pick: boolean;
  direct_reply?: boolean;
  aac_text?: string;
  turn_index?: number;
  title?: string;
  retrieved?: unknown;
}> {
  const body: Record<string, unknown> = { text };
  if (sensing?.emotion) body.emotion = sensing.emotion;
  if (sensing?.hand_gesture) body.hand_gesture = sensing.hand_gesture;
  if (sensing?.head_signal) body.head_signal = sensing.head_signal;
  const phrases = (quickPhrases || [])
    .map((p) => p.trim())
    .filter(Boolean);
  if (phrases.length) body.quick_phrases = phrases;

  const res = await fetch(
    `${API_BASE}/account/chat/sessions/${encodeURIComponent(sessionId)}/turn`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function pickAccountChatCandidate(
  sessionId: string,
  candidateId: string,
): Promise<{
  aac_text: string;
  partner_text: string;
  turn_index: number;
  turn_count: number;
  max_turns: number;
  chosen: AccountChatCandidate;
}> {
  const res = await fetch(
    `${API_BASE}/account/chat/sessions/${encodeURIComponent(sessionId)}/pick`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ candidate_id: candidateId }),
    },
  );
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function postQuickPhrase(
  sessionId: string,
  text: string,
): Promise<AccountChatMessage> {
  const res = await fetch(
    `${API_BASE}/account/chat/sessions/${encodeURIComponent(sessionId)}/quick`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text }),
    },
  );
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  return data.message as AccountChatMessage;
}

export async function transcribePartnerAudio(
  blob: Blob,
): Promise<{ text: string; provider?: string; model?: string }> {
  const form = new FormData();
  form.append("file", blob, "partner.wav");
  const res = await fetch(`${API_BASE}/account/speech/transcribe`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function speakAacText(
  text: string,
  opts?: {
    voice?: string | null;
    emotion?: string | null;
    signal?: AbortSignal;
    timeoutMs?: number;
  },
): Promise<Blob> {
  const ctrl = new AbortController();
  const onOuterAbort = () => ctrl.abort();
  opts?.signal?.addEventListener("abort", onOuterAbort);
  let timer: ReturnType<typeof setTimeout> | undefined;
  if (opts?.timeoutMs && opts.timeoutMs > 0) {
    timer = setTimeout(() => ctrl.abort(), opts.timeoutMs);
  }
  try {
    const res = await fetch(`${API_BASE}/account/speech/tts`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text,
        voice: opts?.voice || undefined,
        emotion: opts?.emotion || undefined,
      }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(await accountError(res));
    return await res.blob();
  } catch (err) {
    if (ctrl.signal.aborted) {
      throw new Error("TTS request timed out");
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
    opts?.signal?.removeEventListener("abort", onOuterAbort);
  }
}

export async function fetchPhraseAudioStatus(): Promise<{
  status: string;
  done: number;
  total: number;
  current?: string | null;
  message?: string;
}> {
  const res = await fetch(`${API_BASE}/account/speech/phrases/status`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function fetchPhraseAudioClip(
  voice: string,
  phraseId: string,
): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/account/speech/phrases/${encodeURIComponent(voice)}/${encodeURIComponent(phraseId)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
  return res.blob();
}

export async function fetchVoiceSampleClip(voice: string): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/account/speech/voices/${encodeURIComponent(voice)}/sample`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await accountError(res));
  return res.blob();
}

export type VoiceOption = {
  id: string;
  label: string;
  gender: "male" | "female" | string;
};

export async function fetchVoiceOptions(): Promise<{
  voice: string;
  options: VoiceOption[];
  sample_text: string;
}> {
  const res = await fetch(`${API_BASE}/account/voice`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await accountError(res));
  return res.json();
}

export async function setVoicePreference(voice: string): Promise<AccountUser> {
  const res = await fetch(`${API_BASE}/account/voice`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ voice }),
  });
  if (!res.ok) throw new Error(await accountError(res));
  const data = await res.json();
  return data.user as AccountUser;
}
