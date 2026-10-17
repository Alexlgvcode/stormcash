// Money is integer cents everywhere (§0 rule 7); format only for display.
export function dollars(cents: number): string {
  const sign = cents < 0 ? "−" : "";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100).toLocaleString("en-US");
  return `${sign}$${whole}.${String(abs % 100).padStart(2, "0")}`;
}

export function signedDollars(cents: number): string {
  return cents > 0 ? `+${dollars(cents)}` : dollars(cents);
}

/** "4:34 PM" today, "Oct 17, 4:34 PM" on another day: no seconds, no 24-hour clock. */
export function clockTime(unixSeconds: number): string {
  return timeOfDay(new Date(unixSeconds * 1000));
}

export function timeOfDay(d: Date): string {
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}
