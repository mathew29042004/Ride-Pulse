/** Ops → Expenses: claim what you spent for work (with the receipt) and get it back with your
 * next salary; managers approve their team's claims. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Paperclip } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, CardHeader, Field, Input, Modal, PageHeader, Select } from "@/components/ui";
import { api, ApiError, openFile } from "@/lib/api";
import { inr } from "@/lib/format";

interface Claim {
  id: number;
  number: string;
  name: string;
  category_label: string;
  spent_on: string;
  amount: string;
  description: string;
  has_receipt: boolean;
  over_policy: boolean;
  policy_limit: string;
  status: string;
  status_label: string;
  note: string;
}
interface Data {
  mine: Claim[];
  to_approve: Claim[];
  categories: { value: string; label: string; limit: string }[];
}

const tone = (s: string) => (s === "PAID" || s === "APPROVED" ? "brand" : s === "REJECTED" ? "danger" : "warning");

export default function OpsExpenses() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["expenses"], queryFn: () => api.get<Data>("work/expenses/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["expenses"] });
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const [category, setCategory] = useState("FUEL");
  const [spentOn, setSpentOn] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const submit = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("category", category);
      form.append("spent_on", spentOn);
      form.append("amount", amount);
      form.append("description", description);
      if (file) form.append("receipt", file);
      return api.post("work/expenses/", form);
    },
    onSuccess: () => { toast.success("Claim sent to your manager."); setAmount(""); setDescription(""); setFile(null); refresh(); },
    onError: fail,
  });
  const [deciding, setDeciding] = useState<{ claim: Claim; approve: boolean } | null>(null);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: () => api.post(`work/expenses/${deciding!.claim.id}/decide/`, { approve: deciding!.approve, note }),
    onSuccess: () => { setDeciding(null); setNote(""); refresh(); },
    onError: fail,
  });
  const limit = q.data?.categories.find((c) => c.value === category)?.limit;
  const over = limit && amount && Number(amount) > Number(limit);
  return (
    <>
      <PageHeader title="Expenses" subtitle="Claim what you spent for work within 60 days, with the receipt (needed above ₹200). Approved claims are paid with your next salary, tax-free." />
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card className="space-y-3 p-4">
          <CardHeader title="New claim" />
          <Field label="Category">
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              {q.data?.categories.map((c) => <option key={c.value} value={c.value}>{c.label} (up to {inr(c.limit, { whole: true })})</option>)}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Date"><Input type="date" value={spentOn} onChange={(e) => setSpentOn(e.target.value)} /></Field>
            <Field label="Amount (₹)"><Input type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          </div>
          {over && <p className="flex items-center gap-1 text-xs text-amber-600"><AlertTriangle className="size-3.5" /> Over the policy limit: your manager must give a reason to approve it.</p>}
          <Field label="What was it for?"><Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} placeholder="e.g. Diesel for the Thrissur hub audit" /></Field>
          <input ref={fileInput} type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button type="button" variant="secondary" block icon={<Paperclip className="size-4" />} onClick={() => fileInput.current?.click()}>
            {file ? file.name : "Attach the receipt"}
          </Button>
          <Button block disabled={!amount || description.trim().length < 5} loading={submit.isPending} onClick={() => submit.mutate()}>Submit claim</Button>
        </Card>
        <div className="space-y-4">
          {q.data && q.data.to_approve.length > 0 && (
            <Card className="p-4">
              <CardHeader title={`To approve (${q.data.to_approve.length})`} />
              <div className="space-y-2">
                {q.data.to_approve.map((c) => (
                  <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-2 p-2 text-sm">
                    <span>
                      <b>{c.name}</b> · {c.category_label} · {inr(c.amount)} on {c.spent_on}
                      {c.over_policy && <Badge tone="warning" className="ml-1">over {inr(c.policy_limit, { whole: true })} limit</Badge>}
                      <span className="block text-xs text-muted">{c.description}</span>
                    </span>
                    <span className="flex gap-1">
                      {c.has_receipt && <Button size="sm" variant="ghost" onClick={() => openFile(`work/expenses/${c.id}/receipt/`)}>Receipt</Button>}
                      <Button size="sm" onClick={() => (c.over_policy ? setDeciding({ claim: c, approve: true }) : api.post(`work/expenses/${c.id}/decide/`, { approve: true }).then(refresh, fail))}>Approve</Button>
                      <Button size="sm" variant="secondary" onClick={() => setDeciding({ claim: c, approve: false })}>Decline</Button>
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card className="p-4">
            <CardHeader title="My claims" />
            {q.data && !q.data.mine.length && <p className="text-sm text-muted">No claims yet.</p>}
            <div className="space-y-2">
              {q.data?.mine.map((c) => (
                <div key={c.id} className="flex items-center justify-between gap-2 border-b border-line pb-2 text-sm last:border-0">
                  <span>
                    {c.category_label} · {inr(c.amount)} <span className="text-xs text-muted">{c.number} · {c.spent_on}</span>
                    <span className="block text-xs text-muted">{c.description}{c.note ? ` · “${c.note}”` : ""}</span>
                  </span>
                  <Badge tone={tone(c.status)}>{c.status_label}</Badge>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
      <Modal open={!!deciding} onClose={() => setDeciding(null)} title={deciding?.approve ? "Approve over the limit" : "Decline the claim"}>
        <Field label={deciding?.approve ? "Why approve it anyway?" : "Reason (they'll see it)"}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
        </Field>
        <Button className="mt-3" block disabled={note.trim().length < 5} loading={decide.isPending} onClick={() => decide.mutate()}>
          {deciding?.approve ? "Approve" : "Decline"}
        </Button>
      </Modal>
    </>
  );
}
