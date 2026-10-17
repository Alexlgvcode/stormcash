// Full-screen intro slide for the opening beat of the judge demo (spec §21.2,
// 0:00). Copy comes from spec §1 only: no new numbers. No photo by default; a
// build can add one with VITE_INTRO_IMAGE (see README).
import { useEffect, useRef, useState } from "react";

const IMAGE: string | undefined = import.meta.env.VITE_INTRO_IMAGE || undefined;
const IMAGE_CREDIT: string | undefined = import.meta.env.VITE_INTRO_IMAGE_CREDIT || undefined;

const FADE_IN = "motion-safe:animate-intro-in";
// Type scales with the smaller of width and height so the whole slide fits a
// laptop screen and stays readable from 1 m (spec §18).
const TITLE = "text-[clamp(2.25rem,min(3.6vw,6vh),4.5rem)]";
const KICKER = "text-[clamp(1.125rem,min(1.8vw,3vh),2rem)]";
const HEADLINE = "text-[clamp(2rem,min(4.3vw,7vh),5rem)]";
const BODY = "text-[clamp(1.375rem,min(2.4vw,3.9vh),2.75rem)]";

export function Intro({ onClose }: { onClose: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  // Whatever had focus before the slide opened (e.g. the header link) gets it
  // back on close. Read on first render: StrictMode re-runs the effect after
  // focus has already moved to the button.
  const [opener] = useState(() => document.activeElement as HTMLElement | null);

  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      opener?.focus();
    };
  }, [onClose, opener]);

  return (
    // A click anywhere closes it; the button is the keyboard path.
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="intro-title"
      onClick={onClose}
      className="fixed inset-0 z-50 flex cursor-pointer flex-col overflow-y-auto bg-slate-950 px-[6vw] py-[5vh] text-slate-100"
    >
      <div className="flex items-start justify-between gap-6">
        <h2 id="intro-title" className={`${TITLE} font-bold tracking-tight text-white`}>
          Storm<span className="text-sky-400">Cash</span>
        </h2>
        <button
          ref={closeButton}
          className="rounded-lg bg-slate-800 px-4 py-2 text-base font-semibold text-slate-200 hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
        >
          Back to dashboard <kbd className="ml-2 rounded border border-slate-600 px-1.5 font-mono text-sm text-slate-400">Esc</kbd>
        </button>
      </div>

      {IMAGE && (
        // Dimmed behind the right side of the text, so the text layout (and its
        // fit on one screen) is the same with or without a photo.
        <figure className="pointer-events-none absolute inset-y-0 right-0 -z-10 w-3/5">
          <img src={IMAGE} alt="" className="h-full w-full object-cover opacity-40" />
          <div className="absolute inset-0 bg-linear-to-r from-slate-950 to-transparent" />
          {IMAGE_CREDIT && <figcaption className="absolute bottom-3 right-4 text-sm text-slate-400">{IMAGE_CREDIT}</figcaption>}
        </figure>
      )}

      <div className="flex flex-1 items-center py-[3vh]">
        <section className="min-w-0 flex-1">
          <p className={`${KICKER} font-semibold uppercase tracking-wider text-sky-300 ${FADE_IN}`}>
            Hurricane Helene · 2024 · western North Carolina
          </p>
          <ul
            className={`mt-[2.5vh] space-y-[1vh] ${HEADLINE} font-bold leading-tight text-white ${FADE_IN}`}
            style={{ animationDelay: "150ms" }}
          >
            <li>Card readers couldn't connect.</li>
            <li>ATMs ran dry.</li>
            <li>Some shops stayed cash-only for a month.</li>
          </ul>
          <p
            className={`mt-[3.5vh] max-w-[46ch] ${BODY} leading-snug text-balance text-slate-300 ${FADE_IN}`}
            style={{ animationDelay: "300ms" }}
          >
            People had money in the bank and phones with battery, and still couldn't pay.
          </p>
        </section>
      </div>

      <p
        className={`border-t border-slate-800 pt-[3vh] ${BODY} font-medium leading-snug text-balance text-slate-300 ${FADE_IN}`}
        style={{ animationDelay: "450ms" }}
      >
        When a disaster takes out towers and card readers,{" "}
        <span className="text-white">StormCash keeps phones paying local shops</span>, and{" "}
        <span className="text-white">stops cheaters with no internet</span>.
      </p>
    </div>
  );
}
