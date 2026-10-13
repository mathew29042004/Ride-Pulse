import { Link } from "react-router";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-6 p-6 text-center">
      <Logo />
      <div>
        <div className="text-7xl font-bold tracking-tight text-brand">404</div>
        <p className="mt-2 text-muted">This road doesn't go anywhere.</p>
      </div>
      <Link to="/">
        <Button>Back home</Button>
      </Link>
    </div>
  );
}
