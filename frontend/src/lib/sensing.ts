import type { Matrix } from "@mediapipe/tasks-vision";
import type { Affect, GestureName } from "../types";

export function classifyAffect(bs: Record<string, number>): Affect {
  const smileLeft = bs["mouthSmileLeft"] ?? 0;
  const smileRight = bs["mouthSmileRight"] ?? 0;
  const browDownL = bs["browDownLeft"] ?? 0;
  const browDownR = bs["browDownRight"] ?? 0;
  const squintL = bs["eyeSquintLeft"] ?? 0;
  const squintR = bs["eyeSquintRight"] ?? 0;
  const jawOpen = bs["jawOpen"] ?? 0;
  const browInnerUp = bs["browInnerUp"] ?? 0;

  if (jawOpen > 0.4 && browInnerUp > 0.5) return "SURPRISED";
  if (browDownL > 0.4 || browDownR > 0.4) return "FRUSTRATED";
  if (squintL > 0.5 && squintR > 0.5) return "FRUSTRATED";
  if (smileLeft > 0.5 && smileRight > 0.5) return "HAPPY";
  return "NEUTRAL";
}

export function mapGestureLabel(label: string): GestureName | null {
  switch (label) {
    case "Thumb_Up":
      return "THUMBS_UP";
    case "Thumb_Down":
      return "THUMBS_DOWN";
    case "Pointing_Up":
      return "POINTING_UP";
    case "Closed_Fist":
      return "CLOSED_FIST";
    case "Open_Palm":
      return "OPEN_PALM";
    case "Victory":
      return "VICTORY";
    case "ILoveYou":
      return "I_LOVE_YOU";
    default:
      return null;
  }
}

export type HeadSignal = "HEAD_SHAKE" | "HEAD_NOD";

export interface HeadDebug {
  pitch: number;
  yaw: number;
  roll: number;
  crossings: number;
}

interface AnglePoint {
  pitch: number;
  yaw: number;
  t: number;
}

const RAD2DEG = 180 / Math.PI;

function extractAngles(data: Float32Array | number[]): {
  pitch: number;
  yaw: number;
  roll: number;
} {
  const r20 = data[2],
    r21 = data[6],
    r22 = data[10];
  const r10 = data[1],
    r00 = data[0];
  return {
    pitch: Math.atan2(r21, r22),
    yaw: Math.atan2(-r20, Math.sqrt(r21 * r21 + r22 * r22)),
    roll: Math.atan2(r10, r00),
  };
}

const WINDOW_MS = 1400;
const HOLD_MS = 750;
const REFRACTORY_MS = 900;
const SMOOTH_ALPHA = 0.35;

const SHAKE_RANGE_RAD = 0.06;
const SHAKE_DEADBAND_RAD = 0.012;
const SHAKE_MIN_REVERSALS = 1;
const SHAKE_PEAK_SPEED_RAD_S = 0.55;

const NOD_AMPLITUDE_RAD = 0.07;
const NOD_RETURN_FRAC = 0.35;
const NOD_MAX_YAW_RAD = 0.32;
const NOD_PEAK_SPEED_RAD_S = 0.4;

function median(vals: number[]): number {
  if (vals.length === 0) return 0;
  const s = [...vals].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function countReversals(values: number[], deadband: number): number {
  let reversals = 0;
  let prevDir = 0;
  for (let i = 1; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    if (Math.abs(diff) < deadband) continue;
    const dir = diff > 0 ? 1 : -1;
    if (prevDir !== 0 && dir !== prevDir) reversals++;
    prevDir = dir;
  }
  return reversals;
}

function peakAbsSpeed(points: AnglePoint[], axis: "pitch" | "yaw"): number {
  let peak = 0;
  for (let i = 1; i < points.length; i++) {
    const dt = (points[i].t - points[i - 1].t) / 1000;
    if (dt <= 0) continue;
    const d = Math.abs(points[i][axis] - points[i - 1][axis]) / dt;
    if (d > peak) peak = d;
  }
  return peak;
}

export class HeadPoseTracker {
  private history: AnglePoint[] = [];
  private lastEmitTs = 0;
  private lastSignal: HeadSignal | null = null;
  private smoothPitch: number | null = null;
  private smoothYaw: number | null = null;
  private lastDebug: HeadDebug = { pitch: 0, yaw: 0, roll: 0, crossings: 0 };

  calibrate(): void {}

  process(matrix: Matrix): HeadSignal | null {
    const raw = extractAngles(matrix.data);
    const now = performance.now();

    if (this.smoothPitch === null) {
      this.smoothPitch = raw.pitch;
      this.smoothYaw = raw.yaw;
    } else {
      this.smoothPitch += SMOOTH_ALPHA * (raw.pitch - this.smoothPitch);
      this.smoothYaw! += SMOOTH_ALPHA * (raw.yaw - this.smoothYaw!);
    }

    const pitch = this.smoothPitch;
    const yaw = this.smoothYaw!;

    this.history.push({ pitch, yaw, t: now });
    this.history = this.history.filter((p) => p.t >= now - WINDOW_MS);
    this.updateDebug(pitch, yaw, raw.roll);

    if (this.lastSignal && now - this.lastEmitTs < HOLD_MS) {
      return this.lastSignal;
    }

    if (now - this.lastEmitTs < REFRACTORY_MS) return null;
    if (this.history.length < 5) return null;

    const shake = this.detectShake();
    if (shake) {
      this.lastEmitTs = now;
      this.lastSignal = shake;
      this.history = this.history.slice(-3);
      return shake;
    }

    const nod = this.detectNod();
    if (nod) {
      this.lastEmitTs = now;
      this.lastSignal = nod;
      this.history = this.history.slice(-3);
      return nod;
    }

    this.lastSignal = null;
    return null;
  }

  private updateDebug(pitch: number, yaw: number, roll: number): void {
    this.lastDebug = {
      pitch: +(pitch * RAD2DEG).toFixed(1),
      yaw: +(yaw * RAD2DEG).toFixed(1),
      roll: +(roll * RAD2DEG).toFixed(1),
      crossings: countReversals(
        this.history.map((p) => p.yaw),
        SHAKE_DEADBAND_RAD,
      ),
    };
  }

  private detectShake(): HeadSignal | null {
    const yaws = this.history.map((p) => p.yaw);
    const range = Math.max(...yaws) - Math.min(...yaws);
    if (range < SHAKE_RANGE_RAD) return null;

    const reversals = countReversals(yaws, SHAKE_DEADBAND_RAD);
    const speed = peakAbsSpeed(this.history, "yaw");
    const pitchRange =
      Math.max(...this.history.map((p) => p.pitch)) -
      Math.min(...this.history.map((p) => p.pitch));

    if (pitchRange > range * 1.35) return null;

    if (reversals >= SHAKE_MIN_REVERSALS || speed >= SHAKE_PEAK_SPEED_RAD_S) {
      return "HEAD_SHAKE";
    }
    return null;
  }

  private detectNod(): HeadSignal | null {
    const pitches = this.history.map((p) => p.pitch);
    const baseline = median(pitches.slice(0, Math.min(8, pitches.length)));
    const deviations = pitches.map((p) => p - baseline);
    const peakIdx = deviations.reduce(
      (best, d, i) => (Math.abs(d) > Math.abs(deviations[best]) ? i : best),
      0,
    );
    const peakDev = deviations[peakIdx];
    const amp = Math.abs(peakDev);
    if (amp < NOD_AMPLITUDE_RAD) return null;

    const yawRange =
      Math.max(...this.history.map((p) => p.yaw)) -
      Math.min(...this.history.map((p) => p.yaw));
    if (yawRange > NOD_MAX_YAW_RAD && yawRange > amp * 1.2) return null;

    const after = deviations.slice(peakIdx);
    const minAbsAfter =
      after.length > 0 ? Math.min(...after.map((d) => Math.abs(d))) : amp;
    const returned = minAbsAfter <= amp * (1 - NOD_RETURN_FRAC);
    const speed = peakAbsSpeed(this.history, "pitch");
    if (!returned && speed < NOD_PEAK_SPEED_RAD_S) return null;

    return "HEAD_NOD";
  }

  get debug(): HeadDebug {
    return this.lastDebug;
  }

  reset(): void {
    this.history = [];
    this.lastEmitTs = 0;
    this.lastSignal = null;
    this.smoothPitch = null;
    this.smoothYaw = null;
  }

  get calibrated(): boolean {
    return true;
  }
}
