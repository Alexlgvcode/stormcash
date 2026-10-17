// Small outline icons for the sidebar and status lines, drawn in currentColor.
const PATHS = {
  intro: ["M3 4h18v12H3z", "M12 16v4", "M8 20h8", "M10 8l4 2-4 2z"],
  accounts: ["M3 10h18", "M5 10v8", "M9.5 10v8", "M14.5 10v8", "M19 10v8", "M3 21h18", "M12 3l9 5H3z"],
  cases: ["M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z", "M9 12l2 2 4-4"],
  town: ["M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z", "M9 4v14", "M15 6v14"],
  droid: ["M5 8h14v11H5z", "M12 4v4", "M9 13h.01", "M15 13h.01", "M9 16.5h6", "M2 12v3", "M22 12v3"],
  evals: ["M4 20h16", "M7 16v-4", "M12 16V6", "M17 16v-7"],
  check: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M8 12l3 3 5-6"],
  cross: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9 9l6 6", "M15 9l-6 6"],
  alert: ["M12 3l10 18H2z", "M12 10v4", "M12 17.5h.01"],
  minus: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M8 12h8"],
  reset: ["M3 12a9 9 0 1 0 3-6.7", "M3 4v5h5"],
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
