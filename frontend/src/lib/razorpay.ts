/**
 * Razorpay Standard Checkout. The script is loaded only when a top-up actually uses it, from
 * Razorpay's own CDN (required by Razorpay: Checkout handles card and UPI details itself, so
 * they never touch Ride Pulse's servers).
 */
import { api } from "./api";

interface CheckoutResult {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface Order {
  key_id: string;
  order_id: string;
  amount: number;
  currency: string;
  prefill: { name: string; email: string; contact: string };
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open(): void; on(event: string, cb: (e: unknown) => void): void };
  }
}

let loading: Promise<void> | null = null;

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve();
    script.onerror = () => {
      loading = null;
      reject(new Error("Couldn't load Razorpay Checkout. Check your connection."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/** Pay `amount` rupees into the wallet. Resolves after the server has verified and credited. */
export async function razorpayTopUp(amount: number): Promise<"paid" | "dismissed"> {
  const [order] = await Promise.all([api.post<Order>("wallet/razorpay-order/", { amount }), loadCheckout()]);
  const result = await new Promise<CheckoutResult | null>((resolve, reject) => {
    const checkout = new window.Razorpay!({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: "Ride Pulse",
      description: "Wallet top-up",
      prefill: order.prefill,
      theme: { color: "#6366f1" },
      handler: (response: CheckoutResult) => resolve(response),
      modal: { ondismiss: () => resolve(null) },
    });
    checkout.on("payment.failed", (e) => reject(new Error((e as { error?: { description?: string } }).error?.description ?? "Payment failed.")));
    checkout.open();
  });
  if (!result) return "dismissed";
  await api.post("wallet/razorpay-confirm/", result);
  return "paid";
}
