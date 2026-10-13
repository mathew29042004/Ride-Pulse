/** Web Push on this device: subscribe/unsubscribe and report what's possible. */
import { api, request } from "./api";

export type PushStatus = "unsupported" | "disabled" | "blocked" | "off" | "on";

function keyBytes(base64url: string): Uint8Array {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

export async function pushStatus(vapidKey: string | undefined): Promise<PushStatus> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (!vapidKey) return "disabled";
  if (Notification.permission === "denied") return "blocked";
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  return subscription ? "on" : "off";
}

export async function enablePush(vapidKey: string): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are blocked. Allow them in the browser's site settings.");
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(vapidKey) as BufferSource }));
  await api.post("/api/v1/push/subscription/", subscription.toJSON());
}

export async function disablePush(): Promise<void> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  await request("/api/v1/push/subscription/", { method: "DELETE", body: { endpoint: subscription.endpoint } }).catch(() => undefined);
  await subscription.unsubscribe();
}
