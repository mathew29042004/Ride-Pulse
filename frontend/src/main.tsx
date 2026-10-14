import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { Toaster } from "sonner";

import { configQuery, MapsProvider } from "./components/map";
import { LayoutProvider } from "./lib/layout";
import { ApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { getLanguage, useLanguage } from "./lib/i18n";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

document.documentElement.lang = getLanguage();

/** Re-render every screen in the new language when the rider or driver switches. */
function Routes() {
  const [language] = useLanguage();
  return <RouterProvider key={language} router={router} />;
}

// Know the map provider before the first render so maps don't swap renderers mid-flight.
queryClient
  .prefetchQuery(configQuery)
  .catch(() => undefined)
  .finally(() =>
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <MapsProvider>
              <LayoutProvider>
                <Routes />
              </LayoutProvider>
            </MapsProvider>
            <Toaster position="top-center" richColors closeButton />
          </AuthProvider>
        </QueryClientProvider>
      </StrictMode>,
    ),
  );

// Installable app + offline shell (production builds only; the dev server reloads by itself).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
