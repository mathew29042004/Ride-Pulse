/**
 * Team chat for staff: channels (#general, departments, states), direct messages, groups, and a
 * thread on every task and meeting. Live over /ws/chat/; @name mentions notify people.
 * Reply to a message (quoted), react, pin, edit or delete your own for 5 minutes, turn a message
 * into a task; each person's status (online, away, in a meeting, on leave); "Seen" in DMs.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Bot, ClipboardPlus, FileText, Hash, MessagesSquare, Paperclip, Pencil, Pin, Plus, Reply, Search, Send, SmilePlus, Trash2, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Button, Input, Modal } from "@/components/ui";
import { api, ApiError, fileUrl, openFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSocket } from "@/lib/ws";

interface Row {
  id: number;
  kind: "CHANNEL" | "DIRECT" | "GROUP" | "TASK" | "MEETING" | "TICKET" | "INCIDENT";
  title: string;
  topic: string;
  last_message_at: string | null;
  last_body: string;
  last_author: string | null;
  unread: number;
}
interface Msg {
  id: number;
  author_id: number | null;
  author: string | null;
  body: string;
  mentions: number[];
  automated: boolean;
  system: boolean;
  created_at: string;
  conversation_id?: number;
  conversation?: string;
  file: { name: string; size: number; image: boolean; url: string } | null;
  deleted?: boolean;
  edited?: boolean;
  pinned?: boolean;
  reactions?: Record<string, number[]>;
  reply_to?: { id: number; author: string; body: string } | null;
}
interface Thread {
  id: number;
  kind: Row["kind"];
  title: string;
  topic: string;
  task_id: number | null;
  meeting_id: number | null;
  ticket_id: number | null;
  members: { id: number; name: string; status?: string }[];
  messages: Msg[];
  pinned?: Msg[];
  reactions?: string[];
  seen_at?: string | null;
}

const STATUS_DOT: Record<string, string> = { online: "bg-emerald-500", away: "bg-slate-400", "in a meeting": "bg-amber-500", "on leave": "bg-rose-400" };
interface Person {
  id: number;
  name: string;
  title: string;
  handle: string;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
const SECTIONS: [string, Row["kind"][]][] = [
  ["War rooms", ["INCIDENT"]],
  ["Channels", ["CHANNEL"]],
  ["Direct messages & groups", ["DIRECT", "GROUP"]],
  ["Task, meeting & ticket threads", ["TASK", "MEETING", "TICKET"]],
];
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export default function OpsChat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const inbox = useQuery({ queryKey: ["chat"], queryFn: () => api.get<{ conversations: Row[]; unread: number }>("chat/"), refetchInterval: 30_000 });
  const current = id ? Number(id) : (inbox.data?.conversations[0]?.id ?? null);
  const thread = useQuery({ queryKey: ["chat", current], queryFn: () => api.get<Thread>(`chat/${current}/messages/`), enabled: current != null });
  const [starting, setStarting] = useState<"" | "dm" | "group">("");
  const [q, setQ] = useState("");
  const found = useQuery({ queryKey: ["chat", "search", q], queryFn: () => api.get<Msg[]>(`chat/search/?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 2 });

  const [typing, setTyping] = useState<Record<number, { name: string; until: number }>>({});
  useSocket("/ws/chat/", (msg) => {
    if (msg.event === "chat.typing") {
      const d = msg.data as { conversation_id: number; name: string };
      setTyping((old) => ({ ...old, [d.conversation_id]: { name: d.name, until: Date.now() + 4000 } }));
      return;
    }
    if (msg.event === "chat.update") {
      const u = msg.data as Msg;
      qc.setQueryData<Thread>(["chat", u.conversation_id], (old) => (old ? { ...old, messages: old.messages.map((x) => (x.id === u.id ? { ...x, ...u } : x)) } : old));
      if (u.conversation_id === current) qc.invalidateQueries({ queryKey: ["chat", u.conversation_id] });
      return;
    }
    if (msg.event !== "chat.message") return;
    const m = msg.data as Msg;
    setTyping((old) => ({ ...old, [m.conversation_id!]: { name: "", until: 0 } }));
    qc.setQueryData<Thread>(["chat", m.conversation_id], (old) => (old && !old.messages.some((x) => x.id === m.id) ? { ...old, messages: [...old.messages, m] } : old));
    // Mark it read first when it's the open conversation, then refresh the unread counts.
    const read = m.conversation_id === current ? api.post(`chat/${current}/read/`).catch(() => undefined) : Promise.resolve();
    read.then(() => qc.invalidateQueries({ queryKey: ["chat"], exact: true }));
  });

  return (
    <div className="-m-4 flex h-[calc(100dvh-64px)] overflow-hidden border-line md:-m-6">
      <aside className={clsx("w-full shrink-0 overflow-y-auto border-r border-line md:w-72", id && "hidden md:block")}>
        <div className="flex items-center gap-2 p-3">
          <MessagesSquare className="size-5 text-brand" />
          <span className="font-bold">Team chat</span>
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" icon={<Plus className="size-4" />} onClick={() => setStarting("dm")}>
              Message
            </Button>
            <Button size="sm" variant="ghost" icon={<Users className="size-4" />} onClick={() => setStarting("group")} aria-label="New group" />
          </div>
        </div>
        <div className="relative px-3 pb-2">
          <Search className="absolute left-5 top-2.5 size-4 text-muted" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search messages and files" className="pl-8" aria-label="Search messages" />
        </div>
        {q.trim().length >= 2 && (
          <div className="mb-2 border-b border-line pb-2">
            {found.data?.length === 0 && <div className="px-3 text-xs text-muted">Nothing found.</div>}
            {found.data?.map((m) => (
              <button key={m.id} onClick={() => { setQ(""); navigate(`/ops/chat/${m.conversation_id}`); }} className="block w-full px-3 py-1.5 text-left text-xs hover:bg-surface-2">
                <span className="font-semibold">{m.conversation}</span> · {m.author ?? "system"} · {new Date(m.created_at).toLocaleDateString()}
                <span className="block truncate text-muted">{m.file ? `📎 ${m.file.name} ` : ""}{m.body}</span>
              </button>
            ))}
          </div>
        )}
        {SECTIONS.map(([label, kinds]) => {
          const rows = (inbox.data?.conversations ?? []).filter((r) => kinds.includes(r.kind));
          if (!rows.length) return null;
          return (
            <div key={label} className="mb-2">
              <div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
              {rows.map((r) => (
                <button key={r.id} onClick={() => navigate(`/ops/chat/${r.id}`)} className={clsx("flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-2", r.id === current && "bg-surface-2")}>
                  {r.kind === "CHANNEL" ? <Hash className="size-4 shrink-0 text-muted" /> : <span className="size-4 shrink-0" />}
                  <span className="min-w-0 flex-1">
                    <span className={clsx("block truncate", r.unread > 0 && "font-bold")}>{r.kind === "CHANNEL" ? r.title.replace(/^#/, "") : r.title}</span>
                    {r.kind !== "CHANNEL" && r.last_body && (
                      <span className="block truncate text-xs text-muted">
                        {r.last_author ? `${r.last_author}: ` : ""}
                        {r.last_body}
                      </span>
                    )}
                  </span>
                  {r.unread > 0 && <span className="rounded-full bg-brand px-1.5 text-[11px] font-bold text-on-brand">{r.unread}</span>}
                </button>
              ))}
            </div>
          );
        })}
      </aside>
      {current != null && thread.data ? (
        <Conversation key={current} thread={thread.data} me={user?.id ?? 0} typing={typing[current]?.until > Date.now() ? typing[current].name : ""} onBack={() => navigate("/ops/chat")} />
      ) : (
        <div className="hidden flex-1 items-center justify-center text-sm text-muted md:flex">Pick a conversation.</div>
      )}
      {starting && (
        <StartModal
          mode={starting}
          onClose={() => setStarting("")}
          onOpened={(cid) => {
            setStarting("");
            qc.invalidateQueries({ queryKey: ["chat"], exact: true });
            navigate(`/ops/chat/${cid}`);
          }}
        />
      )}
    </div>
  );
}

function Conversation({ thread, me, typing, onBack }: { thread: Thread; me: number; typing: string; onBack: () => void }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [replyTo, setReplyTo] = useState<Msg | null>(null);
  const [editing, setEditing] = useState<Msg | null>(null);
  const [tasking, setTasking] = useState<Msg | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const lastTyping = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const [, tick] = useState(0);
  useEffect(() => {
    // Re-render after the typing notice expires.
    if (!typing) return;
    const timer = setTimeout(() => tick((n) => n + 1), 4100);
    return () => clearTimeout(timer);
  }, [typing]);
  const onType = (value: string) => {
    setBody(value);
    if (value && Date.now() - lastTyping.current > 3000) {
      lastTyping.current = Date.now();
      api.post(`chat/${thread.id}/typing/`).catch(() => undefined);
    }
  };
  const added = (m: Msg) =>
    qc.setQueryData<Thread>(["chat", thread.id], (old) => (old && !old.messages.some((x) => x.id === m.id) ? { ...old, messages: [...old.messages, m] } : old));
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      if (body.trim()) form.append("body", body.trim());
      return api.post<Msg>(`chat/${thread.id}/upload/`, form);
    },
    onSuccess: (m) => {
      setBody("");
      added(m);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, and an effect must
    // return nothing or a cleanup function.
    end.current?.scrollIntoView({ block: "end" });
  }, [thread.messages.length]);
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["chat"], exact: true }); // opening marked it read
  }, [thread.id, qc]);
  const send = useMutation({
    mutationFn: () =>
      editing ? api.post<Msg>(`chat-messages/${editing.id}/edit/`, { body }) : api.post<Msg>(`chat/${thread.id}/send/`, { body, reply_to: replyTo?.id ?? null }),
    onSuccess: (m) => {
      setBody("");
      setReplyTo(null);
      if (editing) {
        setEditing(null);
        qc.invalidateQueries({ queryKey: ["chat", thread.id] });
        return;
      }
      qc.setQueryData<Thread>(["chat", thread.id], (old) => (old && !old.messages.some((x) => x.id === m.id) ? { ...old, messages: [...old.messages, m] } : old));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const act = useMutation({
    mutationFn: ({ id, path, data }: { id: number; path: string; data?: object }) => api.post<Msg>(`chat-messages/${id}/${path}/`, data ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat", thread.id] }),
    onError: (err) => toast.error(errorText(err)),
  });
  const makeTask = useMutation({
    mutationFn: ({ id, assignee }: { id: number; assignee: number }) => api.post(`chat-messages/${id}/task/`, { assignee_id: assignee }),
    onSuccess: () => {
      toast.success("Task created.");
      setTasking(null);
      qc.invalidateQueries({ queryKey: ["chat", thread.id] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const editable = (m: Msg) => m.author_id === me && !m.deleted && Date.now() - new Date(m.created_at).getTime() < 5 * 60_000;
  const statusOf = useMemo(() => Object.fromEntries(thread.members.map((p) => [p.id, p.status ?? ""])), [thread.members]);
  const other = thread.kind === "DIRECT" ? thread.members.find((p) => p.id !== me) : undefined;
  const lastMine = [...thread.messages].reverse().find((m) => m.author_id === me);
  const seen = !!(thread.seen_at && lastMine && new Date(thread.seen_at) >= new Date(lastMine.created_at));
  const mention = body.match(/@([\w.-]*)$/)?.[1];
  const suggestions = mention != null ? thread.members.filter((p) => p.id !== me && p.name.toLowerCase().replace(/\s+/g, ".").includes(mention.toLowerCase())).slice(0, 5) : [];
  const offerAll = mention != null && thread.members.length > 2 && "all".startsWith(mention.toLowerCase());
  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <button onClick={onBack} className="text-sm text-muted md:hidden">
          ←
        </button>
        <div className="min-w-0">
          <div className="truncate font-semibold">{thread.title}</div>
          <div className="truncate text-xs text-muted">
            {other?.status && (
              <span className="mr-1 inline-flex items-center gap-1">
                <span className={clsx("size-1.5 rounded-full", STATUS_DOT[other.status])} /> {other.status} ·
              </span>
            )}
            {thread.topic || `${thread.members.length} people`}
            {thread.task_id && " · task thread"}
            {thread.meeting_id && " · meeting thread"}
            {thread.ticket_id && " · ticket thread (staff only)"}
          </div>
        </div>
      </header>
      {(thread.pinned?.length ?? 0) > 0 && (
        <div className="border-b border-line bg-amber-500/5 px-4 py-1.5 text-xs">
          {thread.pinned!.slice(0, 2).map((p) => (
            <div key={p.id} className="flex items-center gap-1.5 truncate">
              <Pin className="size-3 shrink-0 text-amber-600" />
              <span className="font-semibold">{p.author}:</span>
              <span className="truncate">{p.body}</span>
              <button className="ml-auto shrink-0 text-muted hover:text-fg" onClick={() => act.mutate({ id: p.id, path: "pin", data: { pinned: false } })} aria-label="Unpin">
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {thread.messages.length === 0 && <p className="py-10 text-center text-sm text-muted">No messages yet. Say hello 👋</p>}
        {thread.messages.map((m) =>
          m.system ? (
            <div key={m.id} className="text-center text-xs text-muted">
              {m.body}
            </div>
          ) : (
            <div key={m.id} className={clsx("group flex items-center gap-1", m.author_id === me && "flex-row-reverse")}>
              <div className={clsx("relative max-w-[75%] rounded-2xl px-3 py-2 text-sm", m.author_id === me ? "bg-brand text-on-brand" : "bg-surface-2", m.mentions.includes(me) && "ring-2 ring-amber-400", m.deleted && "opacity-60")}>
                {m.reply_to && (
                  <div className={clsx("mb-1 rounded-lg border-l-2 px-2 py-1 text-xs", m.author_id === me ? "border-white/60 bg-white/10" : "border-brand bg-surface")}>
                    <span className="font-semibold">{m.reply_to.author}</span> {m.reply_to.body}
                  </div>
                )}
                {m.author_id !== me && (
                  <div className="mb-0.5 flex items-center gap-1 text-xs font-semibold">
                    {m.author_id && statusOf[m.author_id] && <span className={clsx("size-1.5 rounded-full", STATUS_DOT[statusOf[m.author_id]])} title={statusOf[m.author_id]} />}
                    {m.author}
                    {m.automated && (
                      <span className="flex items-center gap-0.5 font-normal text-muted" title="A pre-set reply from a demo employee nobody is signed in as">
                        <Bot className="size-3" /> demo reply
                      </span>
                    )}
                  </div>
                )}
                {m.file && <Attachment file={m.file} mine={m.author_id === me} />}
                {m.deleted ? <div className="italic">Message deleted</div> : m.body && <div className="whitespace-pre-wrap break-words">{m.body}</div>}
                <div className={clsx("mt-0.5 flex items-center justify-end gap-1 text-[10px]", m.author_id === me ? "text-on-brand/70" : "text-muted")}>
                  {m.pinned && <Pin className="size-2.5" />}
                  {m.edited && !m.deleted && "edited ·"} {time(m.created_at)}
                  {m.id === lastMine?.id && thread.kind === "DIRECT" && (seen ? " · Seen" : " · Sent")}
                </div>
                {Object.entries(m.reactions ?? {}).filter(([, ids]) => ids.length).length > 0 && (
                  <div className="absolute -bottom-3 left-2 flex gap-0.5">
                    {Object.entries(m.reactions ?? {})
                      .filter(([, ids]) => ids.length)
                      .map(([e, ids]) => (
                        <button key={e} onClick={() => act.mutate({ id: m.id, path: "react", data: { emoji: e } })} className={clsx("rounded-full border px-1.5 text-[11px] text-fg shadow-sm", ids.includes(me) ? "border-brand bg-brand-soft" : "border-line bg-surface")}>
                          {e} {ids.length}
                        </button>
                      ))}
                  </div>
                )}
              </div>
              {!m.deleted && (
                <div className="relative flex shrink-0 gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                  <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => setPicking(picking === m.id ? null : m.id)} aria-label="React"><SmilePlus className="size-3.5" /></button>
                  <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => { setReplyTo(m); setEditing(null); }} aria-label="Reply"><Reply className="size-3.5" /></button>
                  <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => act.mutate({ id: m.id, path: "pin", data: { pinned: !m.pinned } })} aria-label={m.pinned ? "Unpin" : "Pin"}><Pin className="size-3.5" /></button>
                  <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => setTasking(m)} aria-label="Turn into a task"><ClipboardPlus className="size-3.5" /></button>
                  {editable(m) && (
                    <>
                      <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => { setEditing(m); setReplyTo(null); setBody(m.body); }} aria-label="Edit"><Pencil className="size-3.5" /></button>
                      <button className="rounded-full p-1 text-muted hover:bg-surface-3" onClick={() => act.mutate({ id: m.id, path: "remove" })} aria-label="Delete"><Trash2 className="size-3.5" /></button>
                    </>
                  )}
                  {picking === m.id && (
                    <div className="absolute bottom-full z-10 mb-1 flex gap-0.5 rounded-full border border-line bg-surface p-1 shadow-lg">
                      {(thread.reactions ?? ["👍", "❤️", "😂", "🎉", "🙏", "👀", "✅"]).map((e) => (
                        <button key={e} className="rounded-full px-1 text-base hover:bg-surface-3" onClick={() => { act.mutate({ id: m.id, path: "react", data: { emoji: e } }); setPicking(null); }}>
                          {e}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ),
        )}
        <div ref={end} />
      </div>
      {typing && <div className="px-4 pb-1 text-xs text-muted">{typing} is typing…</div>}
      {(replyTo || editing) && (
        <div className="flex items-center gap-2 border-t border-line bg-surface-2 px-4 py-1.5 text-xs">
          {replyTo ? <Reply className="size-3.5 text-brand" /> : <Pencil className="size-3.5 text-brand" />}
          <span className="truncate">
            {replyTo ? <><span className="font-semibold">Replying to {replyTo.author ?? "Ride Pulse"}:</span> {replyTo.body}</> : "Editing your message"}
          </span>
          <button className="ml-auto text-muted hover:text-fg" onClick={() => { setReplyTo(null); if (editing) { setEditing(null); setBody(""); } }} aria-label="Cancel"><X className="size-3.5" /></button>
        </div>
      )}
      {tasking && (
        <Modal open onClose={() => setTasking(null)} title="Turn into a task">
          <p className="mb-2 text-sm text-muted">“{tasking.body.slice(0, 120)}”. Who should do it? (Due in 2 days.)</p>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {thread.members.map((p) => (
              <button key={p.id} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2" onClick={() => makeTask.mutate({ id: tasking.id, assignee: p.id })}>
                <span className={clsx("size-1.5 rounded-full", STATUS_DOT[p.status ?? ""] ?? "bg-slate-300")} /> {p.name}{p.id === me && " (me)"}
              </button>
            ))}
          </div>
        </Modal>
      )}
      <form
        className="relative flex gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) send.mutate();
        }}
      >
        {(suggestions.length > 0 || offerAll) && (
          <div className="absolute bottom-full left-3 mb-1 rounded-xl border border-line bg-surface p-1 shadow-lg">
            {offerAll && (
              <button type="button" onClick={() => setBody(body.replace(/@[\w.-]*$/, "@all "))} className="block w-full rounded-lg px-3 py-1 text-left text-sm hover:bg-surface-2">
                <span className="font-semibold">@all</span> <span className="text-xs text-muted">notify everyone here</span>
              </button>
            )}
            {suggestions.map((p) => (
              <button
                type="button"
                key={p.id}
                onClick={() => setBody(body.replace(/@[\w.-]*$/, `@${p.name.split(" ")[0].toLowerCase()} `))}
                className="block w-full rounded-lg px-3 py-1 text-left text-sm hover:bg-surface-2"
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.csv,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.target.value = "";
          }}
        />
        <Button type="button" variant="ghost" icon={<Paperclip className="size-4" />} loading={upload.isPending} onClick={() => fileInput.current?.click()} aria-label="Share a file" />
        <Input value={body} onChange={(e) => onType(e.target.value)} placeholder={`Message ${thread.title}  ·  @name, a name, or @all`} className="flex-1" aria-label="Message" />
        <Button type="submit" icon={<Send className="size-4" />} loading={send.isPending} disabled={!body.trim()} aria-label="Send" />
      </form>
    </section>
  );
}

function StartModal({ mode, onClose, onOpened }: { mode: "dm" | "group"; onClose: () => void; onOpened: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Person[]>([]);
  const [name, setName] = useState("");
  const people = useQuery({ queryKey: ["chat", "people", q], queryFn: () => api.get<Person[]>(`chat/people/?q=${encodeURIComponent(q)}`) });
  const open = useMutation({
    mutationFn: (p: Person) => api.post<{ id: number }>("chat/direct/", { user_id: p.id }),
    onSuccess: (r) => onOpened(r.id),
    onError: (err) => toast.error(errorText(err)),
  });
  const group = useMutation({
    mutationFn: () => api.post<{ id: number }>("chat/group/", { name, member_ids: picked.map((p) => p.id) }),
    onSuccess: (r) => onOpened(r.id),
    onError: (err) => toast.error(errorText(err)),
  });
  const pickedIds = useMemo(() => new Set(picked.map((p) => p.id)), [picked]);
  return (
    <Modal
      open
      onClose={onClose}
      title={mode === "dm" ? "New message" : "New group"}
      footer={
        mode === "group" ? (
          <Button block loading={group.isPending} disabled={picked.length < 2 || name.trim().length < 2} onClick={() => group.mutate()}>
            Create group ({picked.length + 1} people)
          </Button>
        ) : undefined
      }
    >
      {mode === "group" && <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Group name, e.g. Monsoon prep" className="mb-2" />}
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, email or title" autoFocus />
      {picked.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{picked.map((p) => <span key={p.id} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{p.name}</span>)}</div>}
      <div className="mt-2 max-h-72 overflow-y-auto">
        {(people.data ?? []).map((p) => (
          <button
            key={p.id}
            onClick={() => (mode === "dm" ? open.mutate(p) : setPicked(pickedIds.has(p.id) ? picked.filter((x) => x.id !== p.id) : [...picked, p]))}
            className={clsx("flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2", pickedIds.has(p.id) && "bg-brand/10")}
          >
            <span>
              {p.name}
              <span className="block text-xs text-muted">
                {p.title} · @{p.handle}
              </span>
            </span>
            {pickedIds.has(p.id) && <span className="text-xs text-brand">added</span>}
          </button>
        ))}
      </div>
    </Modal>
  );
}

/** A shared file: images load inline (fetched with your sign-in); other files download. */
function Attachment({ file, mine }: { file: NonNullable<Msg["file"]>; mine: boolean }) {
  const path = file.url.replace(/^\/api\/v1\//, "");
  const img = useQuery({ queryKey: ["chat", "file", path], queryFn: () => fileUrl(path), enabled: file.image, staleTime: Infinity });
  if (file.image && img.data) {
    return (
      <button type="button" onClick={() => openFile(path)} className="mb-1 block" aria-label={`Open ${file.name}`}>
        <img src={img.data} alt={file.name} className="max-h-60 rounded-lg" />
      </button>
    );
  }
  return (
    <button type="button" onClick={() => openFile(path)} className={clsx("mb-1 flex items-center gap-2 rounded-lg px-2 py-1.5 text-left", mine ? "bg-white/15" : "bg-surface")}>
      <FileText className="size-4 shrink-0" />
      <span className="min-w-0">
        <span className="block truncate text-xs font-semibold">{file.name}</span>
        <span className="text-[10px] opacity-70">{(file.size / 1024).toFixed(0)} KB</span>
      </span>
    </button>
  );
}
