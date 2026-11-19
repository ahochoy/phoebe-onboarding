import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "../routes";
// The routes load these lazily. Importing them here loads them before a test
// renders, so a slow first import under a busy suite cannot outlast findBy's
// timeout. The lazy boundary itself is still exercised.
import "../session/SessionGate";
import "../pages/Employee";
import "../pages/Admin";

export function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/** Renders the real route table at `path` in a memory router. */
export function renderApp(path = "/", client: QueryClient = makeClient(), basename?: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path], basename });
  const utils = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...utils, router, client };
}
