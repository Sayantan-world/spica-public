export type Affect = "HAPPY" | "FRUSTRATED" | "NEUTRAL" | "SURPRISED";
export type GestureName =
  | "THUMBS_UP"
  | "THUMBS_DOWN"
  | "POINTING_UP"
  | "CLOSED_FIST"
  | "OPEN_PALM"
  | "VICTORY"
  | "I_LOVE_YOU";
export type HeadSignal = "HEAD_SHAKE" | "HEAD_NOD";

export interface HeadDebug {
  pitch: number;
  yaw: number;
  roll: number;
  crossings: number;
}

export interface SensingState {
  affect: Affect | null;
  gestureTag: GestureName | null;
  headSignal: HeadSignal | null;
  headCalibrated: boolean;
  headDebug: HeadDebug;
}
