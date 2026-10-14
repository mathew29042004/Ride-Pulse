/**
 * Trip audio recording, kept on this device: the microphone is recorded with MediaRecorder,
 * encrypted with the trip key from the server (AES-256-GCM, Web Crypto), and stored in
 * IndexedDB. Nothing leaves the device unless the user sends it to the safety team. Recordings
 * older than 7 days are deleted automatically.
 */

import { api } from "@/lib/api";

const DB = "ridepulse-recordings";
const STORE = "recordings";
const KEEP_MS = 7 * 86_400_000;

export interface StoredRecording {
  id: string;
  tripId: number;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
  mime: string;
  seconds: number;
  createdAt: number;
  shared?: boolean;
}

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore(STORE, { keyPath: "id" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const conn = await db();
  return new Promise((resolve, reject) => {
    const request = fn(conn.transaction(STORE, mode).objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function listRecordings(tripId?: number): Promise<StoredRecording[]> {
  const all = (await tx("readonly", (s) => s.getAll())) as StoredRecording[];
  return all.filter((r) => tripId === undefined || r.tripId === tripId).sort((a, b) => b.createdAt - a.createdAt);
}

export async function deleteOldRecordings(): Promise<void> {
  const old = (await listRecordings()).filter((r) => Date.now() - r.createdAt > KEEP_MS);
  await Promise.all(old.map((r) => tx("readwrite", (s) => s.delete(r.id))));
}

function b64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function bytesToB64(bytes: Uint8Array): string {
  let text = "";
  bytes.forEach((b) => (text += String.fromCharCode(b)));
  return btoa(text);
}

/** Start recording; call the returned function to stop, encrypt and save on the device. */
export async function startRecording(tripId: number): Promise<() => Promise<StoredRecording>> {
  const { key } = await api.post<{ key: string }>(`trips/${tripId}/recording/start/`);
  const cryptoKey = await crypto.subtle.importKey("raw", b64ToBytes(key), "AES-GCM", false, ["encrypt"]);
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const started = Date.now();
  recorder.start(1000);

  return () =>
    new Promise((resolve, reject) => {
      recorder.onstop = async () => {
        try {
          stream.getTracks().forEach((t) => t.stop());
          const audio = await new Blob(chunks, { type: recorder.mimeType }).arrayBuffer();
          const iv = crypto.getRandomValues(new Uint8Array(12));
          const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, cryptoKey, audio);
          const saved: StoredRecording = {
            id: crypto.randomUUID(),
            tripId,
            iv: iv.buffer,
            ciphertext,
            mime: recorder.mimeType || "audio/webm",
            seconds: Math.round((Date.now() - started) / 1000),
            createdAt: Date.now(),
          };
          await tx("readwrite", (s) => s.put(saved));
          resolve(saved);
        } catch (err) {
          reject(err);
        }
      };
      recorder.stop();
    });
}

/** Upload one saved (still encrypted) recording to the safety team. */
export async function shareRecording(recording: StoredRecording): Promise<{ ticket_number: string }> {
  const form = new FormData();
  form.append("file", new Blob([recording.ciphertext]), "recording.bin");
  form.append("iv", bytesToB64(new Uint8Array(recording.iv)));
  form.append("mime_type", recording.mime);
  form.append("duration", String(recording.seconds));
  const result = await api.post<{ ticket_number: string }>(`trips/${recording.tripId}/recording/share/`, form);
  await tx("readwrite", (s) => s.put({ ...recording, shared: true }));
  return result;
}
