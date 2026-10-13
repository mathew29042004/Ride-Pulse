import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button, Input, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, titleCase } from "@/lib/format";
import type { DriverDocument } from "@/lib/types";

export function DocumentRow({ doc, driverName, driverId }: { doc: DriverDocument; driverName?: string; driverId?: number }) {
  const qc = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const review = useMutation({
    mutationFn: (approve: boolean) => api.post(`drivers/documents/${doc.id}/review/`, { approve, reason }),
    onSuccess: (_, approve) => {
      toast.success(approve ? "Document approved" : "Document rejected");
      setRejecting(false);
      qc.invalidateQueries({ queryKey: ["drivers"] });
      qc.invalidateQueries({ queryKey: ["verification"] });
    },
    onError: (err) => toast.error((err as Error).message),
  });
  return (
    <div className="flex flex-wrap items-center gap-3 px-5 py-3">
      <div className="min-w-48 flex-1">
        <div className="text-sm font-semibold">{titleCase(doc.doc_type)}</div>
        <div className="text-xs text-muted">
          {driverName && driverId && (
            <Link to={`/ops/drivers/${driverId}`} className="font-semibold text-fg hover:underline">
              {driverName}
            </Link>
          )}
          {driverName && " · "}…{doc.number_last4 || "????"} · expires {date(doc.expires_on)} · uploaded {date(doc.created_at)}
        </div>
        {doc.rejection_reason && <div className="text-xs text-danger">{doc.rejection_reason}</div>}
      </div>
      {doc.file && (
        <a href={doc.file} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs font-semibold text-muted hover:text-fg">
          View file <ExternalLink className="size-3" />
        </a>
      )}
      <StatusBadge status={doc.status} />
      {doc.status === "PENDING" &&
        (rejecting ? (
          <div className="flex w-full gap-2 md:w-auto">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for rejection" className="!py-1.5" />
            <Button size="sm" variant="danger" onClick={() => review.mutate(false)} disabled={!reason.trim()} loading={review.isPending}>
              Reject
            </Button>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button size="sm" variant="brand" icon={<Check className="size-3.5" />} onClick={() => review.mutate(true)} loading={review.isPending}>
              Approve
            </Button>
            <Button size="sm" variant="outline" icon={<X className="size-3.5" />} onClick={() => setRejecting(true)}>
              Reject
            </Button>
          </div>
        ))}
    </div>
  );
}
