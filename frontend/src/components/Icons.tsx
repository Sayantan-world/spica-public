import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 18, ...props }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
    ...props,
  };
}

export function IconSend(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22 11 13 2 9 22 2z" />
    </svg>
  );
}

export function IconMic(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <path d="M12 19v4" />
      <path d="M8 23h8" />
    </svg>
  );
}

export function IconMicOff(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M1 1l22 22" />
      <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
      <path d="M17 16.95A7 7 0 0 1 5 12v-2" />
      <path d="M19 10v2a7 7 0 0 1-.11 1.23" />
      <path d="M12 19v4" />
      <path d="M8 23h8" />
    </svg>
  );
}

export function IconSpeaker(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M11 5 6 9H2v6h4l5 4V5z" />
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
    </svg>
  );
}

export function IconEar(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 15a6 6 0 1 1 10.5 3.9" />
      <path d="M12 9a3 3 0 0 1 3 3c0 2-3 2.5-3 5" />
      <path d="M12 19v2" />
    </svg>
  );
}

export function IconEye(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export function IconDatabase(props: IconProps) {
  return (
    <svg {...base(props)}>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5" />
      <path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6" />
    </svg>
  );
}

export function IconLogout(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

export function IconVoice(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <path d="M9 21h6" />
      <path d="M12 17v4" />
    </svg>
  );
}

export function IconSun(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="M4.93 4.93l1.41 1.41" />
      <path d="M17.66 17.66l1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="M4.93 19.07l1.41-1.41" />
      <path d="M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3a7 7 0 0 0 11.5 11.5z" />
    </svg>
  );
}

export function IconGrid(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

export function IconMoreInfo(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

export function IconWait(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  );
}

export function IconComeHere(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3v10" />
      <path d="M8 9l4 4 4-4" />
      <path d="M5 17h14" />
      <path d="M7 21h10" />
    </svg>
  );
}

export function IconX(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M18 6 6 18" />
      <path d="M6 6l12 12" />
    </svg>
  );
}

export function IconHelp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5" />
      <path d="M12 17h.01" />
    </svg>
  );
}

export function IconBathroom(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 12h16" />
      <path d="M6 12v6a2 2 0 0 0 2 2h0a2 2 0 0 0 2-2v-1h4v1a2 2 0 0 0 2 2h0a2 2 0 0 0 2-2v-6" />
      <path d="M7 12V7a2 2 0 0 1 2-2h6" />
      <path d="M15 5v2" />
    </svg>
  );
}

export function IconFood(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2" />
      <path d="M7 2v20" />
      <path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3z" />
      <path d="M21 15v7" />
    </svg>
  );
}

export function IconDrink(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 2h8l1 4H7l1-4z" />
      <path d="M7 6h10l-1.2 14.1A2 2 0 0 1 13.8 22h-3.6a2 2 0 0 1-2-1.9L7 6z" />
      <path d="M12 10v6" />
    </svg>
  );
}

export function IconExcuseMe(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 14v-1a4 4 0 0 1 4-4h1" />
      <path d="M9 9V5.5A2.5 2.5 0 0 1 11.5 3h0A2.5 2.5 0 0 1 14 5.5V12" />
      <path d="M14 10.5V8a2 2 0 1 1 4 0v6" />
      <path d="M18 12v-1.5a2 2 0 1 1 4 0V16a6 6 0 0 1-6 6h-2a6 6 0 0 1-5.2-3" />
    </svg>
  );
}

export function IconThumbsUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 10v10" />
      <path d="M15 5.5V10h4.2a2 2 0 0 1 1.9 2.5l-1.4 6A2 2 0 0 1 17.8 20H7V10l4-7a2 2 0 0 1 2.6.8L15 5.5z" />
    </svg>
  );
}

export function IconThumbsDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M17 14V4" />
      <path d="M9 18.5V14H4.8a2 2 0 0 1-1.9-2.5l1.4-6A2 2 0 0 1 6.2 4H17v10l-4 7a2 2 0 0 1-2.6-.8L9 18.5z" />
    </svg>
  );
}
