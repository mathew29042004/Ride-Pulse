import { useEffect, useRef, useState } from "react";

import { tokens } from "./api";

export interface SocketMessage<T = unknown> {
  event: string;
  data: T;
}

/**
 * Subscribe to a Ride Pulse WebSocket channel (e.g. `/ws/trips/42/`).
 *
 * Reconnects with exponential backoff. Returns whether the socket is live, so callers can poll
 * more often while it isn't (real-time is an enhancement; every screen also works by polling).
 */
export function useSocket(path: string | null, onMessage: (msg: SocketMessage) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!path) return;
    let socket: WebSocket | null = null;
    let retry = 0;
    let openedAt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const token = tokens.access ? `?token=${encodeURIComponent(tokens.access)}` : "";
      socket = new WebSocket(`${protocol}://${location.host}${path}${token}`);
      socket.onopen = () => {
        openedAt = Date.now();
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (closed || event.code === 4403) return;
        // Only a connection that stayed up for a while resets the backoff.
        if (openedAt && Date.now() - openedAt > 10_000) retry = 0;
        openedAt = 0;
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** retry++));
      };
    };
    connect();

    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [path]);

  return connected;
}
