import { clsx } from "clsx";

export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="#0b0f19" />
      <path
        d="M8 34h12l5-12 8 22 6-15 4 5h13"
        fill="none"
        stroke="#10b981"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ className, light = false }: { className?: string; light?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <LogoMark size={30} />
      <span className={clsx("font-[family-name:var(--font-display)] text-lg font-extrabold tracking-tight", light ? "text-white" : "text-fg")}>
        Ride<span className="rp-gradient-text">Pulse</span>
      </span>
    </span>
  );
}
