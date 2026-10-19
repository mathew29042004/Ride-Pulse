import { clsx } from "clsx";
import { Loader2, Star, X } from "lucide-react";
import { AnimatePresence, animate, motion, useMotionValue, type PanInfo } from "motion/react";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, useEffect, useId, useRef, useState } from "react";

import { initials } from "@/lib/format";
import { useLayout } from "@/lib/layout";

export { clsx as cx };

// --- Buttons -------------------------------------------------------------------------------

type Variant = "primary" | "brand" | "secondary" | "ghost" | "danger" | "outline";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-ink text-ink-fg shadow-[0_6px_16px_-8px_rgb(15_23_42/0.55)] hover:opacity-90",
  brand: "bg-[image:var(--gradient-brand)] text-on-brand shadow-[0_8px_20px_-8px_rgb(16_185_129/0.75)] hover:brightness-105 hover:shadow-[0_10px_24px_-8px_rgb(16_185_129/0.85)]",
  secondary: "bg-surface-3 text-fg hover:bg-line",
  ghost: "text-fg hover:bg-surface-3",
  danger: "bg-danger text-white hover:opacity-90",
  outline: "border border-line bg-surface text-fg hover:bg-surface-2",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "min-h-13 py-2.5 px-6 text-base gap-2 rounded-2xl whitespace-normal text-center leading-snug",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  block?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, block, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center font-semibold whitespace-nowrap transition active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        block && "w-full",
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export function IconButton({
  className,
  children,
  label,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex size-10 items-center justify-center rounded-full bg-surface text-fg shadow-[var(--shadow-float)] transition hover:bg-surface-2 active:scale-95",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// --- Form fields ---------------------------------------------------------------------------

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label?: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={clsx("block", className)}>
      {label && <span className="label">{label}</span>}
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-danger">{error}</span>
      ) : (
        hint && <span className="mt-1 block text-xs text-muted">{hint}</span>
      )}
    </label>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={clsx("input", className)} {...rest} />;
});

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx("input min-h-24 resize-y", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx("input appearance-none pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50",
        checked ? "bg-brand" : "bg-surface-3",
      )}
    >
      <span
        className={clsx(
          "absolute top-0.5 size-6 rounded-full bg-white shadow transition-all",
          checked ? "left-[22px]" : "left-0.5",
        )}
      />
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode }[];
  className?: string;
}) {
  return (
    <div className={clsx("inline-flex rounded-xl border border-line bg-surface-2 p-1", className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={clsx(
            "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
            option.value === value ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// --- Display -------------------------------------------------------------------------------

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line/70 px-5 py-4">
      <div>
        <h3 className="text-[15px] font-semibold">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

type Tone = "neutral" | "brand" | "warning" | "danger" | "info" | "dark";
const tones: Record<Tone, string> = {
  neutral: "bg-surface-3 text-muted",
  brand: "bg-brand-soft text-brand-strong dark:text-brand-fg",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300",
  danger: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  info: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  dark: "bg-ink text-ink-fg",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone], className)}>
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, Tone> = {
  REQUESTED: "info",
  DRIVER_ASSIGNED: "info",
  DRIVER_ARRIVED: "warning",
  IN_PROGRESS: "brand",
  COMPLETED: "brand",
  CANCELLED: "danger",
  NO_DRIVER_FOUND: "neutral",
  ONLINE: "brand",
  ON_TRIP: "info",
  OFFLINE: "neutral",
  APPROVED: "brand",
  PENDING: "warning",
  UNDER_REVIEW: "warning",
  PENDING_DOCUMENTS: "neutral",
  REJECTED: "danger",
  SUSPENDED: "danger",
  EXPIRED: "danger",
  OPEN: "warning",
  IN_PROGRESS_TICKET: "info",
  WAITING_ON_USER: "neutral",
  RESOLVED: "brand",
  CLOSED: "neutral",
  ACKNOWLEDGED: "info",
  PAID: "brand",
  FAILED: "danger",
  DUES: "danger",
  URGENT: "danger",
  HIGH: "warning",
  NORMAL: "info",
  LOW: "neutral",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={STATUS_TONES[status] ?? "neutral"}>{label ?? status.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("size-5 animate-spin text-muted", className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-surface-3", className)} />;
}

export function Avatar({ name, size = 40, className }: { name: string; size?: number; className?: string }) {
  const hue = [...name].reduce((acc, c) => acc + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className={clsx("flex shrink-0 items-center justify-center rounded-full font-semibold text-white", className)}
      style={{ width: size, height: size, fontSize: size * 0.38, background: `linear-gradient(135deg, hsl(${hue} 55% 45%), hsl(${(hue + 40) % 360} 60% 35%))` }}
    >
      {initials(name) || "?"}
    </div>
  );
}

export function Stars({ value, size = 14 }: { value: number | string; size?: number }) {
  const n = typeof value === "string" ? Number.parseFloat(value) : value;
  return (
    <span className="inline-flex items-center gap-1 font-semibold">
      <Star style={{ width: size, height: size }} className="fill-amber-400 text-amber-400" />
      {Number.isFinite(n) ? n.toFixed(2) : "—"}
    </span>
  );
}

export function StarInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex justify-center gap-2">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" onClick={() => onChange(n)} aria-label={`${n} stars`} className="transition active:scale-90">
          <Star className={clsx("size-9", n <= value ? "fill-amber-400 text-amber-400" : "text-line")} />
        </button>
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-surface-3 text-muted">{icon}</div>}
      <p className="font-semibold">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "brand" | "warning" | "danger" | "info";
}) {
  const iconTone = {
    neutral: "bg-surface-3 text-fg",
    brand: "bg-gradient-to-br from-emerald-400 to-teal-600 text-white shadow-[0_6px_14px_-6px_rgb(16_185_129/0.7)]",
    warning: "bg-gradient-to-br from-amber-300 to-orange-500 text-white shadow-[0_6px_14px_-6px_rgb(245_158_11/0.7)]",
    danger: "bg-gradient-to-br from-rose-400 to-pink-600 text-white shadow-[0_6px_14px_-6px_rgb(225_29_72/0.6)]",
    info: "bg-gradient-to-br from-sky-400 to-indigo-500 text-white shadow-[0_6px_14px_-6px_rgb(14_165_233/0.6)]",
  }[tone];
  return (
    <Card className="group relative overflow-hidden p-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-float)]">
      <div className="pointer-events-none absolute -top-10 -right-10 size-28 rounded-full bg-brand/5 transition group-hover:bg-brand/10" />
      <div className="relative flex items-center justify-between">
        <span className="text-xs font-medium text-muted">{label}</span>
        {icon && <span className={clsx("flex size-9 items-center justify-center rounded-xl", iconTone)}>{icon}</span>}
      </div>
      <div className="relative mt-3 font-[family-name:var(--font-display)] text-[28px] leading-none font-bold tracking-tight tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

export function KeyValue({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

// --- Overlays ------------------------------------------------------------------------------

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    // Keyboard and screen-reader users land inside the dialog, stay there, and go back to where
    // they were when it closes.
    const before = document.activeElement as HTMLElement | null;
    const focusable = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? [],
      );
    requestAnimationFrame(() => {
      if (panel.current && !panel.current.contains(document.activeElement)) (focusable()[1] ?? panel.current).focus();
    });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const [first, last] = [items[0], items[items.length - 1]];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[1000] flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            ref={panel}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className={clsx("relative w-full overflow-hidden rounded-3xl border border-line bg-surface shadow-2xl", width)}
            initial={{ y: 20, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: 10, scale: 0.98 }}
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 id={titleId} className="font-semibold">{title}</h2>
              <button onClick={onClose} className="rounded-lg p-1 text-muted hover:bg-surface-3" aria-label="Close">
                <X className="size-4" />
              </button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-line bg-surface-2 px-5 py-3">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

type SheetLevel = "peek" | "normal" | "full";
const PEEK_HEIGHT = "136px";
const FULL_HEIGHT = "88%";

/**
 * A mobile bottom sheet over the map, like the ones in ride-hailing apps. Drag (or flick) the
 * handle down to peek at the map, up to expand; tap it to go back to normal. `footer` stays
 * pinned below the scrolling content (e.g. the Book button).
 */
export function Sheet({
  children,
  className,
  footer,
  height = "75%",
}: {
  children: ReactNode;
  className?: string;
  footer?: ReactNode;
  /** Max height at the normal level (a CSS length, e.g. "60%"). */
  height?: string;
}) {
  const [level, setLevel] = useState<SheetLevel>("normal");
  const y = useMotionValue(40);
  const desktop = useLayout().mode === "desktop";
  const maxHeight = level === "peek" ? PEEK_HEIGHT : level === "full" ? FULL_HEIGHT : height;
  // The handle follows the finger, so releasing a drag also lands on it: don't count that as a tap.
  const panned = useRef(false);

  const onPan = (_: PointerEvent, info: PanInfo) => {
    panned.current = true;
    // Follow the finger downwards; resist upwards (the sheet grows on release instead).
    y.set(info.offset.y > 0 ? info.offset.y : info.offset.y * 0.25);
  };
  const onPanEnd = (_: PointerEvent, info: PanInfo) => {
    const travel = info.offset.y + info.velocity.y * 0.15;
    if (travel > 60) setLevel((l) => (l === "full" ? "normal" : "peek"));
    else if (travel < -60) setLevel((l) => (l === "peek" ? "normal" : "full"));
    animate(y, 0, { type: "spring", stiffness: 400, damping: 36 });
  };

  if (desktop) {
    // Big screens: a floating panel on the left of the full-screen map (no dragging needed).
    return (
      <motion.div
        initial={{ opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ type: "spring", stiffness: 320, damping: 32 }}
        className="rp-panel absolute top-4 left-4 z-[500] flex max-h-[calc(100%-32px)] w-[400px] flex-col overflow-hidden rounded-3xl rp-glass shadow-[0_24px_60px_-20px_rgb(15_23_42/0.45)]"
      >
        <div className={clsx("min-h-0 flex-1 overflow-y-auto px-5 pt-5", !footer && "pb-5", className)}>{children}</div>
        {footer && <div className="shrink-0 border-t border-line px-5 pt-3 pb-5">{footer}</div>}
      </motion.div>
    );
  }

  return (
    <motion.div
      style={{ y, maxHeight }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 32 }}
      className="rp-glass relative z-[500] flex flex-col rounded-t-[28px] !border-x-0 !border-b-0 shadow-[0_-12px_32px_-12px_rgb(15_23_42/0.25)] transition-[max-height] duration-300 ease-out will-change-transform"
    >
      <motion.div
        onPan={onPan}
        onPanEnd={onPanEnd}
        onPointerDown={(e) => {
          panned.current = false;
          e.preventDefault(); // no text selection while dragging
        }}
        onTap={() => !panned.current && setLevel((l) => (l === "normal" ? "full" : "normal"))}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setLevel((l) => (l === "normal" ? "full" : "normal"));
          }
        }}
        tabIndex={0}
        role="button"
        aria-label={level === "peek" ? "Expand panel" : "Resize panel"}
        className="shrink-0 cursor-grab touch-none px-5 pt-3 pb-3 active:cursor-grabbing"
      >
        <div className="mx-auto h-1.5 w-10 rounded-full bg-line" />
      </motion.div>
      <div
        className={clsx(
          "min-h-0 flex-1 px-5",
          level === "peek" ? "overflow-hidden" : "overflow-y-auto",
          !footer && "pb-5",
          className,
        )}
      >
        {children}
      </div>
      {footer && level !== "peek" && <div className="shrink-0 border-t border-line px-5 pt-3 pb-5">{footer}</div>}
    </motion.div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="dark relative mb-8 flex flex-wrap items-end justify-between gap-4 overflow-hidden rounded-[var(--radius-card)] bg-[#0b1220] px-6 py-6 text-fg shadow-[0_18px_40px_-20px_rgb(15_23_42/0.6)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_200px_at_0%_0%,rgb(16_185_129/0.35),transparent_60%),radial-gradient(500px_220px_at_100%_120%,rgb(14_165_233/0.28),transparent_60%)]" />
      <div className="relative">
        <h1 className="text-[28px] leading-tight font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="relative flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={clsx("sticky top-0 border-b border-line bg-surface-2/95 px-4 py-2.5 text-xs font-medium text-muted backdrop-blur", className)}>{children}</th>;
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={clsx("border-b border-line/70 px-4 py-2.5 align-middle", className)}>{children}</td>;
}

export function Pagination({ page, count, pageSize = 20, onChange }: { page: number; count: number; pageSize?: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  return (
    <div className="flex items-center justify-between px-4 py-3 text-xs text-muted">
      <span>
        {count.toLocaleString("en-IN")} result{count === 1 ? "" : "s"} · page {page} of {pages}
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </Button>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
