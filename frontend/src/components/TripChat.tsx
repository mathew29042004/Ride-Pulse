/**
 * In-trip chat between the rider and the driver. Messages arrive over the trip's WebSocket (with
 * polling as a fallback), appear instantly when sent (optimistic), and show an unread badge plus
 * a notification while the chat is closed.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, MessageCircle, SendHorizontal, ShieldCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { Avatar } from "@/components/ui";
import { buzz } from "@/lib/alert";
import { api, ApiError } from "@/lib/api";
import { time } from "@/lib/format";
import { useSocket } from "@/lib/ws";

export type Sender = "RIDER" | "DRIVER";

export interface ChatMessage {
  id: number;
  trip_id: number;
  sender: Sender;
  body: string;
  created_at: string;
  pending?: boolean;
}

const QUICK_REPLIES: Record<Sender, string[]> = {
  RIDER: ["I'm at the pickup point", "Please come to the main gate", "I'll be there in 2 min", "Okay 👍"],
  DRIVER: ["I'm on my way", "I've reached the pickup", "Stuck in traffic, 5 more minutes", "Okay 👍"],
};

function useTripChat(tripId: number, me: Sender) {
  const qc = useQueryClient();
  const key = ["trips", String(tripId), "messages"];
  const messages = useQuery({
    queryKey: key,
    queryFn: () => api.get<ChatMessage[]>(`trips/${tripId}/messages/`),
    refetchInterval: 5_000,
  });
  useSocket(`/ws/trips/${tripId}/`, (msg) => {
    if (msg.event !== "message") return;
    const incoming = msg.data as ChatMessage;
    qc.setQueryData<ChatMessage[]>(key, (old = []) => (old.some((m) => m.id === incoming.id) ? old : [...old.filter((m) => !(m.pending && m.body === incoming.body && m.sender === incoming.sender)), incoming]));
  });

  const send = useMutation({
    mutationFn: (body: string) => api.post<ChatMessage>(`trips/${tripId}/messages/`, { body }),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: key });
      const temp: ChatMessage = { id: -Date.now(), trip_id: tripId, sender: me, body, created_at: new Date().toISOString(), pending: true };
      qc.setQueryData<ChatMessage[]>(key, (old = []) => [...old, temp]);
      return { temp };
    },
    onSuccess: (saved, _body, ctx) => {
      qc.setQueryData<ChatMessage[]>(key, (old = []) => {
        const rest = old.filter((m) => m.id !== ctx?.temp.id && m.id !== saved.id);
        return [...rest, saved].sort((a, b) => a.created_at.localeCompare(b.created_at));
      });
    },
    onError: (err, _body, ctx) => {
      qc.setQueryData<ChatMessage[]>(key, (old = []) => old.filter((m) => m.id !== ctx?.temp.id));
      toast.error(err instanceof ApiError ? err.message : "Message not sent.");
    },
  });

  return { list: messages.data ?? [], loaded: messages.isFetched, send };
}

/** The "Message <name>" button plus the full-screen chat it opens (inside the phone screen). */
export function TripChat({
  tripId,
  me,
  otherName,
  canSend,
  compact = false,
}: {
  tripId: number;
  me: Sender;
  otherName: string;
  canSend: boolean;
  /** An icon button (driver panel) instead of the full-width bar (rider). */
  compact?: boolean;
}) {
  const { list, loaded, send } = useTripChat(tripId, me);
  const [open, setOpen] = useState(false);
  const seenKey = `rp.chat.seen.${tripId}`;
  const [seen, setSeen] = useState(() => Number(sessionStorage.getItem(seenKey) ?? 0));
  const unread = list.filter((m) => m.sender !== me && m.id > seen).length;
  const latest = list.at(-1);

  // Opening the chat marks everything read.
  useEffect(() => {
    if (!open || !latest || latest.id <= seen) return;
    setSeen(latest.id);
    sessionStorage.setItem(seenKey, String(latest.id));
  }, [open, latest?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new message while the chat is closed: notify, like a phone would.
  const announced = useRef<number | null>(null);
  useEffect(() => {
    if (!loaded) return;
    if (announced.current === null) {
      announced.current = latest?.id ?? 0; // don't announce the history on first load
      return;
    }
    if (!latest || latest.sender === me || latest.id <= seen || open || latest.id <= announced.current) return;
    announced.current = latest.id;
    buzz([120]);
    toast(`${otherName}: ${latest.body}`, { action: { label: "Reply", onClick: () => setOpen(true) } });
  }, [loaded, latest?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const badge = unread > 0 && (
    <span className="absolute -top-1 -right-1 flex min-w-5 items-center justify-center rounded-full bg-danger px-1 text-[11px] font-bold text-white">{unread}</span>
  );

  return (
    <>
      {compact ? (
        <button onClick={() => setOpen(true)} className="relative flex size-10 items-center justify-center rounded-full bg-surface-3" aria-label={`Message ${otherName}`}>
          <MessageCircle className="size-4" />
          {badge}
        </button>
      ) : (
        <button onClick={() => setOpen(true)} className="relative mt-4 flex w-full items-center gap-3 rounded-2xl bg-surface-2 px-4 py-3 text-left text-sm">
          <MessageCircle className="size-4 text-muted" />
          <span className="flex-1 truncate text-muted">{unread > 0 && latest ? latest.body : `Message ${otherName.split(" ")[0]}…`}</span>
          {badge}
        </button>
      )}
      {/* Rendered over the whole phone screen, not inside the bottom sheet that holds the button. */}
      {createPortal(
        <AnimatePresence>
          {open && <ChatPanel me={me} otherName={otherName} list={list} canSend={canSend} onSend={(body) => send.mutate(body)} onClose={() => setOpen(false)} />}
        </AnimatePresence>,
        document.getElementById("phone-screen") ?? document.body,
      )}
    </>
  );
}

function ChatPanel({
  me,
  otherName,
  list,
  canSend,
  onSend,
  onClose,
}: {
  me: Sender;
  otherName: string;
  list: ChatMessage[];
  canSend: boolean;
  onSend: (body: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, and an effect must
    // return nothing (or a cleanup function).
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [list.length]);

  const submit = (body: string) => {
    const clean = body.trim();
    if (!clean || !canSend) return;
    onSend(clean);
    setText("");
  };

  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", stiffness: 380, damping: 38 }}
      className="rp-chat absolute inset-0 z-[890] flex flex-col bg-canvas"
      role="dialog"
      aria-label={`Chat with ${otherName}`}
    >
      <div className="flex items-center gap-3 border-b border-line bg-surface px-3 py-3 md:pt-12">
        <button onClick={onClose} className="rounded-full p-2 hover:bg-surface-3" aria-label="Close chat">
          <ArrowLeft className="size-5" />
        </button>
        <Avatar name={otherName} size={36} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate font-semibold">{otherName}</div>
          <div className="text-xs text-muted">{me === "RIDER" ? "Your driver" : "Your rider"}</div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-4">
        <div className="mx-auto mb-3 flex max-w-[85%] items-center gap-2 rounded-xl bg-surface-2 px-3 py-2 text-center text-[11px] text-muted">
          <ShieldCheck className="size-4 shrink-0" />
          Chats are kept with the trip so our safety team can help if anything goes wrong.
        </div>
        {list.map((m) => {
          const mine = m.sender === me;
          return (
            <div key={m.id} className={clsx("flex", mine ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-[78%] rounded-2xl px-3.5 py-2 text-sm", mine ? "rounded-br-md bg-ink text-ink-fg" : "rounded-bl-md bg-surface shadow-sm")}>
                <div className="break-words">{m.body}</div>
                <div className={clsx("mt-0.5 text-right text-[10px]", mine ? "opacity-60" : "text-muted")}>{m.pending ? "Sending…" : time(m.created_at)}</div>
              </div>
            </div>
          );
        })}
        {list.length === 0 && <p className="pt-8 text-center text-sm text-muted">No messages yet. Say hello 👋</p>}
        <div ref={bottom} />
      </div>

      {canSend ? (
        <div className="border-t border-line bg-surface px-3 pt-2 pb-4">
          <div className="-mx-3 mb-2 flex gap-2 overflow-x-auto px-3 pb-1">
            {QUICK_REPLIES[me].map((reply) => (
              <button key={reply} onClick={() => submit(reply)} className="shrink-0 rounded-full border border-line px-3 py-1.5 text-xs font-medium hover:bg-surface-2">
                {reply}
              </button>
            ))}
          </div>
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              submit(text);
            }}
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={500}
              placeholder={`Message ${otherName.split(" ")[0]}`}
              className="min-w-0 flex-1 rounded-full bg-surface-2 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
            />
            <button type="submit" disabled={!text.trim()} className="flex size-10 items-center justify-center rounded-full bg-brand text-white disabled:opacity-40" aria-label="Send">
              <SendHorizontal className="size-4" />
            </button>
          </form>
        </div>
      ) : (
        <p className="border-t border-line bg-surface px-4 py-4 text-center text-xs text-muted">Chat is closed for this trip.</p>
      )}
    </motion.div>
  );
}
