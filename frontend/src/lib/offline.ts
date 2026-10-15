/**
 * Offline-first writes. Phones lose signal in tunnels, basements and between towers; the app
 * keeps working and catches up:
 *
 * - GPS fixes taken while offline are saved (IndexedDB) with the time the phone took them, then
 *   replayed in order as one batch (`driver/location/batch/`), so trip distance and Ride Check
 *   still see the real route.
 * - Chat messages written offline are saved and sent, in order, when the connection returns.
 * - Anything older than its shelf life is dropped (a 40-minute-old GPS fix is useless).
 *
 * `useOnline()` and `useQueued()` drive the offline banner.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import { api, ApiError } from "@/lib/api";

type Kind = "location" | "message";
interface Queued {
  id: string;
  kind: Kind;
  path: string;
  body: Record<string, unknown>;
  createdAt: number;
}

const DB = "ridepulse-offline";
const STORE = "outbox";
const SHELF_LIFE: Record<Kind, number> = { location: 25 * 60_000, message: 24 * 3_600_000 };
const listeners = new Set<() => void>();
let queuedCount = 0;

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore(STORE, { keyPath: "id" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const conn = await db();
  return new Promise((resolve, reject) => {
    const req = fn(conn.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function all(): Promise<Queued[]> {
  const rows = (await run("readonly", (s) => s.getAll())) as Queued[];
  return rows.sort((a, b) => a.createdAt - b.createdAt);
}

async function refreshCount() {
  queuedCount = (await all().catch(() => [])).length;
  listeners.forEach((fn) => fn());
}

async function enqueue(kind: Kind, path: string, body: Record<string, unknown>) {
  await run("readwrite", (s) => s.put({ id: crypto.randomUUID(), kind, path, body, createdAt: Date.now() }));
  await refreshCount();
}

/** A network failure (no response at all), as opposed to the server saying no. */
const isOffline = (err: unknown) => !navigator.onLine || (err instanceof TypeError && !(err instanceof ApiError));

/** Send a GPS fix now, or keep it for later with the time it was taken. */
export async function sendLocation(fix: { lat: number; lng: number; heading?: number | null; speed_kmh?: number | null }) {
  const body = { ...fix, heading: fix.heading ?? undefined, recorded_at: new Date().toISOString() };
  if (!navigator.onLine) return enqueue("location", "driver/location/", body);
  try {
    await api.post("driver/location/", body);
  } catch (err) {
    if (isOffline(err)) await enqueue("location", "driver/location/", body);
  }
}

/** Post a chat message, or queue it when offline. Returns false when queued. */
export async function sendMessage<T>(path: string, body: Record<string, unknown>): Promise<T | false> {
  if (!navigator.onLine) {
    await enqueue("message", path, body);
    return false;
  }
  try {
    return await api.post<T>(path, body);
  } catch (err) {
    if (isOffline(err)) {
      await enqueue("message", path, body);
      return false;
    }
    throw err;
  }
}

let flushing = false;

/** Replay everything saved offline: GPS as one ordered batch, messages one by one in order. */
export async function flush(): Promise<void> {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    const now = Date.now();
    const rows = await all();
    const stale = rows.filter((r) => now - r.createdAt > SHELF_LIFE[r.kind]);
    const fixes = rows.filter((r) => r.kind === "location" && !stale.includes(r));
    for (const r of stale) await run("readwrite", (s) => s.delete(r.id));
    if (fixes.length) {
      for (let i = 0; i < fixes.length; i += 200) {
        const chunk = fixes.slice(i, i + 200);
        try {
          await api.post("driver/location/batch/", { fixes: chunk.map((f) => f.body) });
        } catch (err) {
          if (isOffline(err)) return; // still no network: try again later
        }
        for (const f of chunk) await run("readwrite", (s) => s.delete(f.id));
      }
    }
    for (const msg of rows.filter((r) => r.kind === "message" && !stale.includes(r))) {
      try {
        await api.post(msg.path, msg.body);
      } catch (err) {
        if (isOffline(err)) return;
        // The server refused it (e.g. the trip ended): drop it rather than retry forever.
      }
      await run("readwrite", (s) => s.delete(msg.id));
    }
  } finally {
    flushing = false;
    await refreshCount();
  }
}

if (typeof window !== "undefined" && "indexedDB" in window) {
  window.addEventListener("online", () => void flush());
  setInterval(() => void flush(), 30_000);
  void refreshCount().then(() => flush());
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

export function useQueued(): number {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => queuedCount,
  );
}

/** Forget everything saved for the signed-in user (on sign-out). */
export async function clearOffline(): Promise<void> {
  await run("readwrite", (s) => s.clear()).catch(() => undefined);
  await refreshCount();
  navigator.serviceWorker?.controller?.postMessage({ type: "clear-api-cache" });
}
