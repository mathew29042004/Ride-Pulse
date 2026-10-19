/**
 * Team chat for staff: channels (#general, departments, states), direct messages, groups, and a
 * thread on every task and meeting. Live over /ws/chat/; @name mentions notify people.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Bot, FileText, Hash, MessagesSquare, Paperclip, Plus, Search, Send, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Button, Input, Modal } from "@/components/ui";
import { api, ApiError, fileUrl, openFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSocket } from "@/lib/ws";

interface Row {
  id: number;
  kind: "CHANNEL" | "DIRECT" | "GROUP" | "TASK" | "MEETING" | "TICKET";
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
}
interface Thread {
  id: number;
  kind: Row["kind"];
  title: string;
  topic: string;
  task_id: number | null;
  meeting_id: number | null;
  ticket_id: number | null;
  members: { id: number; name: string }[];
  messages: Msg[];
}
interface Person {
  id: number;
  name: string;
  title: string;
  handle: string;
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong.");
const SECTIONS: [string, Row["kind"][]][] = [
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
                  {r.unread > 0 && <span className="rounded-full bg-brand px-1.5 text-[11px] font-bold text-white">{r.unread}</span>}
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
    mutationFn: () => api.post<Msg>(`chat/${thread.id}/send/`, { body }),
    onSuccess: (m) => {
      setBody("");
      qc.setQueryData<Thread>(["chat", thread.id], (old) => (old && !old.messages.some((x) => x.id === m.id) ? { ...old, messages: [...old.messages, m] } : old));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const mention = body.match(/@([\w.-]*)$/)?.[1];
  const suggestions = mention != null ? thread.members.filter((p) => p.id !== me && p.name.toLowerCase().replace(/\s+/g, ".").includes(mention.toLowerCase())).slice(0, 5) : [];
  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <button onClick={onBack} className="text-sm text-muted md:hidden">
          ←
        </button>
        <div className="min-w-0">
          <div className="truncate font-semibold">{thread.title}</div>
          <div className="truncate text-xs text-muted">
            {thread.topic || `${thread.members.length} people`}
            {thread.task_id && " · task thread"}
            {thread.meeting_id && " · meeting thread"}
            {thread.ticket_id && " · ticket thread (staff only)"}
          </div>
        </div>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {thread.messages.length === 0 && <p className="py-10 text-center text-sm text-muted">No messages yet. Say hello 👋</p>}
        {thread.messages.map((m) =>
          m.system ? (
            <div key={m.id} className="text-center text-xs text-muted">
              {m.body}
            </div>
          ) : (
            <div key={m.id} className={clsx("flex", m.author_id === me && "justify-end")}>
              <div className={clsx("max-w-[75%] rounded-2xl px-3 py-2 text-sm", m.author_id === me ? "bg-brand text-white" : "bg-surface-2", m.mentions.includes(me) && "ring-2 ring-amber-400")}>
                {m.author_id !== me && (
                  <div className="mb-0.5 flex items-center gap-1 text-xs font-semibold">
                    {m.author}
                    {m.automated && (
                      <span className="flex items-center gap-0.5 font-normal text-muted" title="A pre-set reply from a demo employee nobody is signed in as">
                        <Bot className="size-3" /> demo reply
                      </span>
                    )}
                  </div>
                )}
                {m.file && <Attachment file={m.file} mine={m.author_id === me} />}
                {m.body && <div className="whitespace-pre-wrap break-words">{m.body}</div>}
                <div className={clsx("mt-0.5 text-right text-[10px]", m.author_id === me ? "text-white/70" : "text-muted")}>{time(m.created_at)}</div>
              </div>
            </div>
          ),
        )}
        <div ref={end} />
      </div>
      {typing && <div className="px-4 pb-1 text-xs text-muted">{typing} is typing…</div>}
      <form
        className="relative flex gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) send.mutate();
        }}
      >
        {suggestions.length > 0 && (
          <div className="absolute bottom-full left-3 mb-1 rounded-xl border border-line bg-surface p-1 shadow-lg">
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
        <Input value={body} onChange={(e) => onType(e.target.value)} placeholder={`Message ${thread.title}  ·  @name to mention`} className="flex-1" aria-label="Message" />
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
    return <img src={img.data} alt={file.name} className="mb-1 max-h-60 cursor-pointer rounded-lg" onClick={() => openFile(path)} />;
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
