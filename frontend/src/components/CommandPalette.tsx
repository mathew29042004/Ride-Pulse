/** Ctrl+K (⌘K on a Mac) anywhere in the console: jump to any page, trip, ticket, driver, rider or
 * colleague. Arrow keys to move, Enter to open, Esc to close. */

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CornerDownLeft, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { api } from "@/lib/api";

interface Hit {
  kind: string;
  title: string;
  detail: string;
  link: string;
}

export function CommandPalette({ pages }: { pages: { to: string; label: string }[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [at, setAt] = useState(0);
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("rp:search", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("rp:search", onOpen);
    };
  }, []);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (open) {
      setQ("");
      setAt(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const remote = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.get<{ results: Hit[] }>(`search/?q=${encodeURIComponent(debounced)}`),
    enabled: open && debounced.trim().length >= 2,
  });
  const hits = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const pageHits: Hit[] = pages
      .filter((p) => !needle || p.label.toLowerCase().includes(needle))
      .slice(0, needle ? 6 : 8)
      .map((p) => ({ kind: "Page", title: p.label, detail: p.to, link: p.to }));
    return [...pageHits, ...(remote.data?.results ?? [])];
  }, [q, pages, remote.data]);
  useEffect(() => setAt(0), [hits.length]);

  if (!open) return null;
  const go = (h: Hit | undefined) => {
    if (!h) return;
    setOpen(false);
    navigate(h.link);
  };
  return (
    <div className="fixed inset-0 z-[1300] flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm" onClick={() => setOpen(false)}>
      <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-surface shadow-[0_40px_80px_-30px_rgb(49_46_129/0.6)]" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Search">
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <Search className="size-5 text-muted" />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setOpen(false);
              else if (e.key === "ArrowDown") { e.preventDefault(); setAt((a) => Math.min(a + 1, hits.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setAt((a) => Math.max(a - 1, 0)); }
              else if (e.key === "Enter") go(hits[at]);
            }}
            placeholder="Search pages, trips, tickets, drivers, riders, people…"
            className="flex-1 bg-transparent text-base outline-none placeholder:text-muted"
            aria-label="Search everything"
          />
          <kbd className="rounded-md border border-line px-1.5 text-[10px] text-muted">Esc</kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-2">
          {hits.length === 0 && <p className="px-3 py-8 text-center text-sm text-muted">{remote.isFetching ? "Searching…" : "Nothing found."}</p>}
          {hits.map((h, i) => (
            <button
              key={`${h.kind}-${h.link}-${i}`}
              onMouseEnter={() => setAt(i)}
              onClick={() => go(h)}
              className={clsx("flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm", i === at && "bg-brand-soft")}
            >
              <span className="w-20 shrink-0 text-[11px] font-semibold tracking-wide text-muted uppercase">{h.kind}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{h.title}</span>
                <span className="block truncate text-xs text-muted">{h.detail}</span>
              </span>
              {i === at && <CornerDownLeft className="size-4 text-muted" />}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
