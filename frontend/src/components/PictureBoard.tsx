import { useEffect, useRef, useState, type ReactNode } from "react";
import { fetchPhraseAudioClip, fetchPhraseAudioStatus } from "../lib/api";
import {
  normalizePhraseVoice,
  PHRASE_ITEMS,
  type PhraseCacheProgress,
} from "../lib/phraseAudioCache";
import {
  IconBathroom,
  IconCheck,
  IconComeHere,
  IconDrink,
  IconExcuseMe,
  IconFood,
  IconHelp,
  IconMoreInfo,
  IconThumbsDown,
  IconThumbsUp,
  IconWait,
  IconX,
} from "./Icons";

type BoardItem = {
  id: string;
  label: string;
  speak: string;
  icon: ReactNode;
};

const ICON = 40;

const ICONS: Record<string, ReactNode> = {
  yes: <IconCheck size={ICON} />,
  no: <IconX size={ICON} />,
  help: <IconHelp size={ICON} />,
  bathroom: <IconBathroom size={ICON} />,
  food: <IconFood size={ICON} />,
  drink: <IconDrink size={ICON} />,
  excuse: <IconExcuseMe size={ICON} />,
  like: <IconThumbsUp size={ICON} />,
  dislike: <IconThumbsDown size={ICON} />,
  more: <IconMoreInfo size={ICON} />,
  wait: <IconWait size={ICON} />,
  come: <IconComeHere size={ICON} />,
};

const LABELS: Record<string, string> = {
  yes: "Yes",
  no: "No",
  help: "Help",
  bathroom: "Bathroom",
  food: "Hungry",
  drink: "Thirsty",
  excuse: "Excuse me",
  like: "I like it",
  dislike: "Don't like",
  more: "Tell me more",
  wait: "Wait",
  come: "Come here",
};

const BOARD: BoardItem[] = PHRASE_ITEMS.map((p) => ({
  id: p.id,
  label: LABELS[p.id] ?? p.speak,
  speak: p.speak,
  icon: ICONS[p.id] ?? null,
}));

interface Props {
  voice?: string | null;
  disabled?: boolean;
  onPhraseSpoken?: (text: string) => void | Promise<void>;
}

export function PictureBoard({
  voice,
  disabled = false,
  onPhraseSpoken,
}: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cache, setCache] = useState<PhraseCacheProgress>({
    status: "idle",
    done: 0,
    total: PHRASE_ITEMS.length * 6,
  });
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const memoryCache = useRef<Map<string, Blob>>(new Map());

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const status = await fetchPhraseAudioStatus();
        if (cancelled) return;
        setCache(status);
        if (status.status !== "ready") {
          timer = setTimeout(poll, 2000);
        }
      } catch {
        if (!cancelled) {
          timer = setTimeout(poll, 4000);
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  async function handlePress(item: BoardItem) {
    if (disabled || activeId) return;
    setError(null);
    setActiveId(item.id);
    // Log into the turn window immediately so generation can use it,
    // even if audio fetch/playback is slow.
    try {
      await onPhraseSpoken?.(item.speak);
    } catch {
      // Dialogue logging errors are surfaced by the chat panel.
    }
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      const selected = normalizePhraseVoice(voice);
      const key = `${selected}::${item.id}`;
      let blob = memoryCache.current.get(key) ?? null;
      if (!blob) {
        try {
          blob = await fetchPhraseAudioClip(selected, item.id);
          memoryCache.current.set(key, blob);
        } catch {
          setActiveId(null);
          setError(
            cache.status === "running"
              ? `Server still building ${selected} phrases…`
              : `Phrase audio for ${selected} is not ready yet`,
          );
          return;
        }
      }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setActiveId(null);
        audioRef.current = null;
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        setActiveId(null);
        setError("Could not play phrase");
      };
      await audio.play();
    } catch (e) {
      setActiveId(null);
      setError(e instanceof Error ? e.message : "Could not play phrase");
    }
  }

  const cacheLine =
    cache.status === "running"
      ? cache.message || `Caching ${cache.done}/${cache.total}…`
      : cache.status === "ready"
        ? null
        : cache.message;

  return (
    <div className="picture-board">
      <p className="picture-board-label">Quick phrases</p>
      {cacheLine && (
        <p className="picture-board-cache" aria-live="polite">
          {cacheLine}
        </p>
      )}
      <div className="picture-board-grid" role="group" aria-label="Picture board">
        {BOARD.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`picture-tile${activeId === item.id ? " speaking" : ""}`}
            disabled={disabled || (activeId !== null && activeId !== item.id)}
            title={item.speak}
            aria-label={item.speak}
            onClick={() => handlePress(item)}
          >
            <span className="picture-tile-icon">{item.icon}</span>
            <span className="picture-tile-label">{item.label}</span>
          </button>
        ))}
      </div>
      {error && <p className="picture-board-error">{error}</p>}
    </div>
  );
}
