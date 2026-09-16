import type { SensingState } from "../types";

const EMOTION_EMOJI: Record<string, string> = {
  HAPPY: "😊",
  FRUSTRATED: "😤",
  NEUTRAL: "😐",
  SURPRISED: "😲",
};

interface Props {
  sensing: SensingState;
  webcamActive: boolean;
}

export function SensingStatus({ sensing, webcamActive }: Props) {
  if (!webcamActive) return null;

  return (
    <div className="sensing-status">
      <div className="sensing-row">
        <span className="sensing-label">Emotion</span>
        <span className="sensing-value">
          {EMOTION_EMOJI[sensing.affect ?? ""] ?? "-"}{" "}
          {sensing.affect ?? "None"}
        </span>
      </div>
      <div className="sensing-row">
        <span className="sensing-label">Hand gesture</span>
        <span className="sensing-value">{sensing.gestureTag ?? "None"}</span>
      </div>
      <div className="sensing-row">
        <span className="sensing-label">Head</span>
        <span className="sensing-value">{sensing.headSignal ?? "None"}</span>
      </div>
      <div className="sensing-row sensing-debug">
        <span className="sensing-label">↳ p/y/r</span>
        <span className="sensing-value">
          {sensing.headDebug.pitch}° / {sensing.headDebug.yaw}° / {sensing.headDebug.roll}°
          {"  "}(x{sensing.headDebug.crossings})
        </span>
      </div>
    </div>
  );
}
