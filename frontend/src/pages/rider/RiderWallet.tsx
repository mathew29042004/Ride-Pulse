import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { AlertTriangle, ArrowDownLeft, ArrowUpRight, CreditCard, Smartphone } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { configQuery } from "@/components/map";
import { Button, Field, Input, Modal, Skeleton } from "@/components/ui";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { dateTime, inr } from "@/lib/format";
import { useWallet } from "@/lib/hooks";
import { razorpayTopUp } from "@/lib/razorpay";
import { t } from "@/lib/i18n";

export default function WalletScreen({ title = "Wallet" }: { title?: string }) {
  const wallet = useWallet();
  const qc = useQueryClient();
  const [topUpOpen, setTopUpOpen] = useState(false);
  const [amount, setAmount] = useState(500);
  const [method, setMethod] = useState<"UPI" | "CARD">("UPI");
  const [payer, setPayer] = useState("");
  const balance = Number(wallet.data?.balance ?? 0);

  const done = (message: string) => {
    toast.success(message);
    qc.invalidateQueries({ queryKey: ["wallet"] });
    qc.invalidateQueries({ queryKey: ["driver"] });
    setTopUpOpen(false);
  };
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : t("Payment failed."));
  type Payment = { status: string; failure_reason: string; amount: string };
  const handle = (p: Payment, ok: string) => (p.status === "SUCCEEDED" ? done(ok) : toast.error(t("Payment declined: {reason}", { reason: p.failure_reason })));

  // With Razorpay keys configured, top-ups go through real (test-mode) Razorpay Checkout.
  const config = useQuery(configQuery);
  const razorpay = !!config.data?.payments?.razorpay_key_id;
  const checkout = useMutation({
    mutationFn: () => razorpayTopUp(amount),
    onSuccess: (outcome) => outcome === "paid" && done(t("{amount} added to your wallet", { amount: inr(amount, { whole: true }) })),
    onError,
  });
  const topUp = useMutation({
    mutationFn: () => api.post<Payment>("wallet/top-up/", { amount, method, payer_reference: payer }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (p) => handle(p, t("{amount} added to your wallet", { amount: inr(p.amount) })),
    onError,
  });
  const payDues = useMutation({
    mutationFn: () => api.post<Payment>("wallet/pay-dues/", { method: "UPI" }, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (p) => handle(p, t("Dues of {amount} cleared", { amount: inr(p.amount) })),
    onError,
  });

  return (
    <div className="h-full overflow-y-auto px-5 pt-5 pb-6">
      <h1 className="text-2xl font-bold tracking-tight">{title}</h1>

      <div className="relative mt-4 overflow-hidden rounded-3xl bg-[#0b0f19] p-5 text-white">
        <div className="absolute -top-10 -right-10 size-40 rounded-full bg-emerald-500/30 blur-2xl" />
        <div className="relative">
          <div className="text-xs font-medium tracking-wide text-white/60 uppercase">{t("Ride Pulse balance")}</div>
          {wallet.isLoading ? (
            <Skeleton className="mt-2 h-9 w-32 bg-white/10" />
          ) : (
            <div className={clsx("mt-1 text-4xl font-bold tracking-tight", balance < 0 && "text-rose-300")}>{inr(balance)}</div>
          )}
          <div className="mt-4 flex gap-2">
            <Button size="sm" variant="brand" onClick={() => setTopUpOpen(true)}>
              {t("Add money")}
            </Button>
            {balance < 0 && (
              <Button size="sm" className="!bg-white !text-[#0b0f19]" onClick={() => payDues.mutate()} loading={payDues.isPending}>
                {t("Pay dues")}
              </Button>
            )}
          </div>
        </div>
      </div>

      {balance < 0 && (
        <div className="mt-4 flex gap-3 rounded-2xl bg-rose-50 p-4 text-sm text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
          <AlertTriangle className="size-5 shrink-0" />
          <p>{t("You have pending dues from an unpaid fare, a cancellation fee or cash commission. Clear them to keep using Ride Pulse.")}</p>
        </div>
      )}

      <h2 className="mt-6 mb-2 text-sm font-semibold">{t("Transactions")}</h2>
      <div className="divide-y divide-line">
        {wallet.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="my-2 h-12" />)}
        {wallet.data?.statement.length === 0 && <p className="py-8 text-center text-sm text-muted">{t("No transactions yet.")}</p>}
        {wallet.data?.statement.map((entry) => {
          const credit = Number(entry.amount) > 0;
          return (
            <div key={entry.id} className="flex items-center gap-3 py-3">
              <span
                className={clsx("flex size-9 items-center justify-center rounded-full", credit ? "bg-brand-soft text-brand-strong" : "bg-surface-3 text-muted")}
              >
                {credit ? <ArrowDownLeft className="size-4" /> : <ArrowUpRight className="size-4" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{entry.kind_label}</div>
                <div className="truncate text-xs text-muted">
                  {entry.description} · {dateTime(entry.created_at)}
                </div>
              </div>
              <div className={clsx("text-sm font-semibold", credit ? "text-brand-strong" : "text-fg")}>
                {credit ? "+" : ""}
                {inr(entry.amount)}
              </div>
            </div>
          );
        })}
      </div>

      <Modal
        open={topUpOpen}
        onClose={() => setTopUpOpen(false)}
        title={t("Add money")}
        footer={
          razorpay ? (
            <Button onClick={() => checkout.mutate()} loading={checkout.isPending} block>
              Pay {inr(amount, { whole: true })} with Razorpay
            </Button>
          ) : (
            <Button onClick={() => topUp.mutate()} loading={topUp.isPending} block>
              Add {inr(amount, { whole: true })}
            </Button>
          )
        }
      >
        <div className="grid grid-cols-3 gap-2">
          {[200, 500, 1000].map((a) => (
            <button
              key={a}
              onClick={() => setAmount(a)}
              className={clsx("rounded-xl border py-2.5 font-semibold", amount === a ? "border-fg bg-surface-2" : "border-line")}
            >
              ₹{a}
            </button>
          ))}
        </div>
        <Field label={t("Amount")} className="mt-3">
          <Input type="number" min={50} max={10000} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
        </Field>
        {razorpay ? (
          <p className="mt-3 text-xs text-muted">{t("Pay by UPI, card, netbanking or wallet in Razorpay's secure checkout.")}</p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {(["UPI", "CARD"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMethod(m)}
                  className={clsx(
                    "flex items-center justify-center gap-2 rounded-xl border py-2.5 text-sm font-semibold",
                    method === m ? "border-fg bg-surface-2" : "border-line",
                  )}
                >
                  {m === "UPI" ? <Smartphone className="size-4" /> : <CreditCard className="size-4" />} {m === "UPI" ? "UPI" : t("Card")}
                </button>
              ))}
            </div>
            <Field label={method === "UPI" ? "UPI ID" : t("Card holder")} hint='Demo gateway: anything containing "fail" is declined.' className="mt-3">
              <Input value={payer} onChange={(e) => setPayer(e.target.value)} placeholder={method === "UPI" ? "name@okbank" : t("Name on card")} />
            </Field>
          </>
        )}
      </Modal>
    </div>
  );
}
