/** Flat side-view illustrations for each ride type (drawn inline, no image assets). */

function Wheel({ cx, cy, r = 4.2 }: { cx: number; cy: number; r?: number }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill="#111827" />
      <circle cx={cx} cy={cy} r={r * 0.45} fill="#d1d5db" />
    </g>
  );
}

function Hatchback({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 64 36" className="h-full w-full">
      <ellipse cx="32" cy="31" rx="26" ry="2.5" fill="rgb(0 0 0 / 0.12)" />
      <path d="M8 26c0-5 1.5-7 6-8l7-6c2-1.6 3.8-2 6.5-2H39c3 0 4.6 1 6.5 3.2L51 18c4 .6 6 2.6 6 6v2z" fill={color} />
      <path d="M23 13.3c1.4-1 2.4-1.3 4.3-1.3h4.2v6H17.6zM34.5 12h4.4c1.9 0 3 .6 4.3 2l3.4 4h-12.1z" fill="#dbeafe" opacity="0.9" />
      <rect x="53" y="20" width="4" height="2" rx="1" fill="#fde68a" />
      <Wheel cx={18} cy={26.5} />
      <Wheel cx={47} cy={26.5} />
    </svg>
  );
}

function Sedan({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 64 36" className="h-full w-full">
      <ellipse cx="32" cy="31" rx="28" ry="2.5" fill="rgb(0 0 0 / 0.12)" />
      <path d="M4 26c0-4 1-6 5-6.6l8.5-1.4 7-5.4c1.8-1.3 3.4-1.6 5.6-1.6h9.6c2.4 0 4 .8 5.6 2.4l4.4 4.6 6.6 1c3 .6 4.2 2.4 4.2 5.4v1.6z" fill={color} />
      <path d="M25.5 13.7c1.2-.9 2.2-1.2 3.8-1.2h4.5v5.9H19.3zM36 12.5h4.3c1.8 0 2.8.6 4 1.8l3.7 4.1H36z" fill="#dbeafe" opacity="0.9" />
      <rect x="56.5" y="21" width="3.5" height="2" rx="1" fill="#fde68a" />
      <Wheel cx={15} cy={26.5} />
      <Wheel cx={49} cy={26.5} />
    </svg>
  );
}

function Suv({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 64 36" className="h-full w-full">
      <ellipse cx="32" cy="31" rx="28" ry="2.5" fill="rgb(0 0 0 / 0.12)" />
      <path d="M5 25.5V17c0-3 1.4-5 4.4-6.5l3.8-2c1.2-.6 2.4-.9 3.8-.9h24.4c2 0 3.4.6 4.8 2.2l5.2 6 6 1.2c2.6.6 3.6 2.4 3.6 5V26z" fill={color} />
      <path d="M14 10.6h11.5v7.4H10.6V14c0-1.8 1.2-3 3.4-3.4zM28 10.6h11.4c1.4 0 2.4.5 3.3 1.5l5 5.9H28z" fill="#dbeafe" opacity="0.9" />
      <rect x="2" y="19" width="2.4" height="5" rx="1" fill="#374151" />
      <rect x="56" y="19.5" width="4" height="2" rx="1" fill="#fde68a" />
      <Wheel cx={16} cy={26.5} r={4.8} />
      <Wheel cx={48} cy={26.5} r={4.8} />
    </svg>
  );
}

function Auto({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 64 36" className="h-full w-full">
      <ellipse cx="32" cy="31" rx="22" ry="2.5" fill="rgb(0 0 0 / 0.12)" />
      <path d="M14 9c0-2 1.4-3.5 3.5-3.5h20c3 0 5 1 6.6 3.4L50 18v8H14z" fill="#111827" />
      <path d="M14 16h36v10H14z" fill={color} />
      <path d="M40 9.5c2 0 3.4.9 4.6 2.7l3.8 5.6H40z" fill="#dbeafe" opacity="0.9" />
      <path d="M18 9.5h18v6.5H18z" fill="#374151" />
      <rect x="48" y="19" width="3" height="2" rx="1" fill="#fde68a" />
      <Wheel cx={20} cy={26.5} />
      <Wheel cx={46} cy={26.5} />
    </svg>
  );
}

function Bike({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 64 36" className="h-full w-full">
      <ellipse cx="32" cy="31" rx="22" ry="2.2" fill="rgb(0 0 0 / 0.12)" />
      <circle cx="16" cy="25" r="6" fill="none" stroke="#111827" strokeWidth="3" />
      <circle cx="48" cy="25" r="6" fill="none" stroke="#111827" strokeWidth="3" />
      <path d="M16 25l9-9h12l4 9M33 16l-3-5h-5M41 16l3-5h5" fill="none" stroke="#374151" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 17c2-3 5-4 9-4h7c2 0 3.5 1 4 3l-7 3H24z" fill={color} />
      <circle cx="34" cy="6" r="3.4" fill={color} />
    </svg>
  );
}

const ART: Record<string, (props: { color: string }) => React.JSX.Element> = {
  BIKE: Bike,
  AUTO: Auto,
  MINI: Hatchback,
  SEDAN: Sedan,
  SUV: Suv,
};

const COLORS: Record<string, string> = {
  BIKE: "#8b5cf6",
  AUTO: "#eab308",
  MINI: "#6366f1",
  SEDAN: "#334155",
  SUV: "#2563eb",
};

export function RideTypeArt({ code, className = "h-9 w-16" }: { code: string; className?: string }) {
  const Art = ART[code] ?? Hatchback;
  return (
    <div className={className}>
      <Art color={COLORS[code] ?? "#6366f1"} />
    </div>
  );
}
