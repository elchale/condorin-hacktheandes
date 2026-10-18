import { useEffect } from "react";
import { syncClock, useNow, type Clock } from "../../lib/clock";

const TZ = "America/Lima";
const dateFmt = new Intl.DateTimeFormat("es-PE", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: TZ });
const timeFmt = new Intl.DateTimeFormat("es-PE", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: TZ });

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Today's date and a ticking Lima clock, as the API sees them; says so when the day is simulated. */
export function TodayClock({ clock }: { clock: Clock | null | undefined }) {
  useEffect(() => syncClock(clock), [clock]);
  const now = useNow(1000);
  // Without a clock block (an API from before it) the device time is shown, which is the real time anyway.
  const date = cap(dateFmt.format(new Date(now)));
  const time = timeFmt.format(new Date(now));
  const simulated = !!clock?.simulated;
  return (
    <section
      aria-label="Fecha de hoy"
      className={`mt-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-3xl p-4 ring-1 sm:p-5 ${
        simulated ? "bg-ambar-claro ring-ambar/40" : "bg-panel ring-line"
      }`}
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-muted">Hoy</p>
        <p className="mt-0.5 text-lg font-black leading-tight tracking-tight sm:text-xl">{date}</p>
      </div>
      <div className="flex items-center gap-3">
        {simulated && (
          <span className="rounded-full bg-ambar px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-white">Fecha simulada</span>
        )}
        <time dateTime={new Date(now).toISOString()} className="tabular-nums text-2xl font-black sm:text-3xl" aria-live="off">
          {time}
        </time>
      </div>
    </section>
  );
}
