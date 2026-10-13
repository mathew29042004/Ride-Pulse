import { RotateCcw } from "lucide-react";
import { isRouteErrorResponse, Link, useRouteError } from "react-router";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui";

/** Shown instead of a blank screen if a page crashes. */
export default function ErrorPage() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "";
  if (error) console.error(error);
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-5 p-6 text-center">
      <Logo />
      <div>
        <h1 className="text-xl font-bold">Something went wrong on this screen</h1>
        <p className="mt-1 max-w-md text-sm text-muted">The rest of Ride Pulse is fine. Reload to try again, or head back home.</p>
        {detail && <p className="mt-3 font-mono text-xs text-muted">{detail}</p>}
      </div>
      <div className="flex gap-2">
        <Button icon={<RotateCcw className="size-4" />} onClick={() => location.reload()}>
          Reload
        </Button>
        <Link to="/">
          <Button variant="outline">Home</Button>
        </Link>
      </div>
    </div>
  );
}
