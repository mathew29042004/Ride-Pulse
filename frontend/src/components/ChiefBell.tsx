/** The chief's crown in the console header: updates and decisions from the chief of staff
 * arrive live (over the chief's own socket) wherever the chief is, as a pop-up with a link,
 * and the badge counts unread updates plus decisions waiting. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown } from "lucide-react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { useSocket } from "@/lib/ws";

interface Inbox {
  unread: number;
  pending: number;
}

export function ChiefBell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["ops", "chief"], queryFn: () => api.get<Inbox>("ops/chief/"), refetchInterval: 60_000 });
  useSocket("/ws/chat/", (msg) => {
    if (msg.event !== "chief_update" && msg.event !== "decision_request") return;
    const d = msg.data as { title: string; kind?: string; sent_by?: string; source?: string; asked_by?: string; order?: string };
    const open = { label: "Open", onClick: () => navigate("/ops/command") };
    if (msg.event === "decision_request") {
      toast.warning(`Decision needed: ${d.title}`, { description: d.order ? `Proposes: ${d.order}` : `From ${d.asked_by}`, action: open, duration: 15_000 });
    } else if (d.kind === "ESCALATION") {
      toast.error(`Escalation: ${d.title}`, { description: `${d.source} · ${d.sent_by}`, action: open, duration: 15_000 });
    } else {
      toast(`${d.kind === "BRIEFING" ? "Briefing" : "Update"}: ${d.title}`, { description: `${d.source} · ${d.sent_by}`, action: open });
    }
    qc.invalidateQueries({ queryKey: ["ops", "chief"] });
  });
  const count = (q.data?.unread ?? 0) + (q.data?.pending ?? 0);
  return (
    <button
      onClick={() => navigate("/ops/command")}
      className="relative flex size-10 items-center justify-center rounded-full hover:bg-surface-3"
      aria-label={count ? `Chief's inbox, ${count} new` : "Chief's inbox"}
    >
      <Crown className="size-5 text-amber-500" />
      {count > 0 && <span className="absolute top-1 right-1 min-w-4 rounded-full bg-amber-500 px-1 text-[10px] leading-4 font-bold text-white">{count}</span>}
    </button>
  );
}
