import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { ApiError } from "./api/client";
import { AboutPhoebe } from "./components/AboutPhoebe";
import { routes } from "./routes";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Client errors (401, 404, ...) will not change on retry.
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function App() {
  const [client] = useState(makeQueryClient);
  const [router] = useState(() =>
    createBrowserRouter(routes, { basename: import.meta.env.BASE_URL.replace(/\/$/, "") || "/" }),
  );
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
      <AboutPhoebe />
    </QueryClientProvider>
  );
}
