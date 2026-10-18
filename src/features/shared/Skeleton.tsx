import { card } from "./ui";

const bar = "skel rounded-md bg-panel-2";

/** Placeholder blocks shown while a member page loads, in the shape of the page that is coming. */
export function Skeleton({ kind, label }: { kind: "panel" | "page"; label: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="space-y-4">
      <span className="sr-only">{label}</span>
      <div aria-hidden className="space-y-2">
        <div className={`${bar} h-3 w-24`} />
        <div className={`${bar} h-7 w-2/3`} />
        <div className={`${bar} h-4 w-5/6`} />
      </div>
      {kind === "panel" && (
        <div aria-hidden className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-2xl bg-panel p-4 ring-1 ring-line">
              <div className={`${bar} h-3 w-20`} />
              <div className={`${bar} mt-3 h-7 w-8`} />
            </div>
          ))}
        </div>
      )}
      <div aria-hidden className={card}>
        <div className={`${bar} h-5 w-3/4`} />
        <div className={`${bar} mt-2 h-4 w-1/2`} />
        <div className={`${bar} mt-5 aspect-[4/3] w-full rounded-xl`} />
        <div className={`${bar} mt-4 h-4 w-2/3`} />
      </div>
    </div>
  );
}
