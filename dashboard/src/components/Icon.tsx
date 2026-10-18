// Small outline icons for status lines, drawn in currentColor.
const PATHS = {
  check: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M8 12l3 3 5-6"],
  cross: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9 9l6 6", "M15 9l-6 6"],
  alert: ["M12 3l10 18H2z", "M12 10v4", "M12 17.5h.01"],
  minus: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M8 12h8"],
  // Navigation
  overview: ["M4 4h7v7H4z", "M13 4h7v4h-7z", "M13 10h7v10h-7z", "M4 13h7v7H4z"],
  network: ["M6 6a2 2 0 1 0 0-.01", "M18 8a2 2 0 1 0 0-.01", "M8 18a2 2 0 1 0 0-.01", "M7.8 7l8.4 1", "M6.5 8l1.2 8", "M9.7 16.9l6.8-7.4"],
  shield: ["M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z", "M9 12l2 2 4-4"],
  ledger: ["M4 5h16", "M4 10h16", "M4 15h16", "M4 20h10"],
  agent: ["M12 3v3", "M5 8h14v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z", "M9 13h.01", "M15 13h.01", "M9.5 17h5"],
  close: ["M6 6l12 12", "M18 6L6 18"],
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
