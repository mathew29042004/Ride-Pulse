/**
 * Full-screen camera scanner for the rider's start code. Uses the browser's native
 * BarcodeDetector where available (Chrome on Android/macOS) and jsQR everywhere else (Safari).
 */

import jsQR from "jsqr";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "@/lib/i18n";

type Detector = { detect(source: CanvasImageSource): Promise<{ rawValue: string }[]> };

export function QrScanner({ onScan, onClose }: { onScan: (text: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  const done = useRef(false);
  const handler = useRef(onScan);
  handler.current = onScan;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | undefined;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const Native = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
    const detector = Native ? new Native({ formats: ["qr_code"] }) : null;

    const found = (text: string) => {
      if (done.current || !text.startsWith("RP1.")) return;
      done.current = true;
      navigator.vibrate?.(80);
      handler.current(text);
    };

    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((s) => {
        stream = s;
        if (!video.current) return;
        video.current.srcObject = s;
        void video.current.play();
        timer = setInterval(async () => {
          const v = video.current;
          if (!v || v.readyState < 2 || done.current) return;
          if (detector) {
            const codes = await detector.detect(v).catch(() => []);
            if (codes[0]) found(codes[0].rawValue);
            return;
          }
          canvas.width = v.videoWidth;
          canvas.height = v.videoHeight;
          ctx?.drawImage(v, 0, 0);
          const image = ctx?.getImageData(0, 0, canvas.width, canvas.height);
          const result = image && jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
          if (result) found(result.data);
        }, 250);
      })
      .catch(() => setError("Camera access is blocked. Allow it in the browser, or enter the rider's PIN instead."));
    if (!navigator.mediaDevices) setError("This browser can't use the camera. Enter the rider's PIN instead.");

    return () => {
      clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return createPortal(
    <div className="absolute inset-0 z-[890] flex flex-col bg-black text-white" role="dialog" aria-label={t("Scan the rider's QR code")}>
      <div className="flex items-center justify-between p-4 md:pt-12">
        <div className="font-semibold">{t("Scan the rider's code")}</div>
        <button onClick={onClose} className="rounded-full bg-white/10 p-2" aria-label={t("Close scanner")}>
          <X className="size-5" />
        </button>
      </div>
      <div className="relative flex flex-1 items-center justify-center overflow-hidden">
        <video ref={video} playsInline muted className="absolute inset-0 size-full object-cover" />
        <div className="relative size-60 rounded-3xl border-4 border-white/90 shadow-[0_0_0_9999px_rgb(0_0_0/0.45)]" />
      </div>
      <p className="p-5 text-center text-sm text-white/80">{error ?? "Point the camera at the QR code on the rider's phone."}</p>
    </div>,
    document.getElementById("phone-screen") ?? document.body,
  );
}
