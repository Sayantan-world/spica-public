/** Picture-board phrase defs + shared server-side audio cache client. */

export const PHRASE_VOICES = [
  "Jason",
  "Leo",
  "Ray",
  "Mia",
  "Aria",
  "Sofia",
] as const;

export type PhraseVoice = (typeof PHRASE_VOICES)[number];

export type PhraseDef = {
  id: string;
  speak: string;
};

export const PHRASE_ITEMS: PhraseDef[] = [
  { id: "yes", speak: "Yes" },
  { id: "no", speak: "No" },
  { id: "help", speak: "Help" },
  { id: "bathroom", speak: "I need the bathroom" },
  { id: "food", speak: "I'm hungry" },
  { id: "drink", speak: "I'm thirsty" },
  { id: "excuse", speak: "Excuse me" },
  { id: "like", speak: "I like it" },
  { id: "dislike", speak: "I don't like it" },
  { id: "more", speak: "Tell me more" },
  { id: "wait", speak: "Wait" },
  { id: "come", speak: "Come here" },
];

export type PhraseCacheProgress = {
  status: "idle" | "running" | "ready" | "error" | string;
  done: number;
  total: number;
  current?: string | null;
  message?: string;
};

export function normalizePhraseVoice(voice: string | null | undefined): PhraseVoice {
  const key = (voice || "Jason").trim().toLowerCase();
  const found = PHRASE_VOICES.find((v) => v.toLowerCase() === key);
  return found ?? "Jason";
}
