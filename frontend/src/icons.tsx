import { ReactNode } from "react";

// Small stroke icon set (24x24 viewBox, currentColor). Decorative by default (aria-hidden); the button carries the label.
const I = ({ children, size = 18 }: { children: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {children}
  </svg>
);

export const IconLogo = () => (
  <I size={20}>
    <path d="M2 12h3l2-6 3 12 3-9 2 3h7" />
  </I>
);
export const IconPoint = () => (
  <I>
    <circle cx="6" cy="16" r="2" />
    <circle cx="18" cy="16" r="2" />
    <path d="M8 16h8M3 20h18" />
  </I>
);
export const IconSection = () => (
  <I>
    <path d="M3 18l5-7 4 4 4-8 5 11z" />
    <path d="M3 21h18" />
  </I>
);
export const IconTerrain = () => (
  <I>
    <path d="M12 3l9 5-9 5-9-5z" />
    <path d="M3 13l9 5 9-5M3 17l9 5 9-5" />
  </I>
);
export const IconAudio = () => (
  <I>
    <path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2" />
  </I>
);
export const IconProjects = () => (
  <I>
    <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
  </I>
);
export const IconLab = () => (
  <I>
    <path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3" />
    <path d="M8 15h8" />
  </I>
);
export const IconDiag = () => (
  <I>
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <path d="M8 13l2-3 2 4 2-6 2 5" />
  </I>
);
export const IconSearch = () => (
  <I size={16}>
    <circle cx="11" cy="11" r="6" />
    <path d="M20 20l-4-4" />
  </I>
);
export const IconSun = () => (
  <I size={16}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" />
  </I>
);
export const IconMoon = () => (
  <I size={16}>
    <path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z" />
  </I>
);
export const IconUndo = () => (
  <I size={16}>
    <path d="M9 14L4 9l5-5" />
    <path d="M4 9h10a6 6 0 010 12h-3" />
  </I>
);
export const IconRedo = () => (
  <I size={16}>
    <path d="M15 14l5-5-5-5" />
    <path d="M20 9H10a6 6 0 000 12h3" />
  </I>
);
export const IconPanelLeft = () => (
  <I size={16}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </I>
);
export const IconPanelRight = () => (
  <I size={16}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M15 4v16" />
  </I>
);
export const IconPlay = () => (
  <I size={14}>
    <path d="M7 4l13 8-13 8z" />
  </I>
);
export const IconReset = () => (
  <I size={12}>
    <path d="M4 12a8 8 0 108-8H7M7 4L4 7l3 3" />
  </I>
);
export const IconPreset = () => (
  <I size={16}>
    <path d="M5 4h11l3 3v13H5z" />
    <path d="M8 4v5h7V4M8 20v-6h8v6" />
  </I>
);
