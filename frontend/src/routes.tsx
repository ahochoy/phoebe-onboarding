import { Navigate, type RouteObject } from "react-router";
import { PetalLoader } from "./components/PetalLoader";
import { Landing } from "./pages/Landing";

// Shown while a deep link (e.g. a reload on /employee) fetches its chunks.
const loading = (
  <main className="flex min-h-screen flex-col items-center justify-center gap-3">
    <PetalLoader size={64} label="Getting Phoebe ready…" />
  </main>
);

// Only the landing page is in the entry chunk. The signed-in shell (the chat
// runtime) and each page load on first visit, so the password screen stays small.
export const routes: RouteObject[] = [
  { path: "/", element: <Landing /> },
  {
    hydrateFallbackElement: loading,
    lazy: async () => ({ Component: (await import("./session/SessionGate")).SessionGate }),
    children: [
      {
        path: "/employee",
        lazy: async () => ({ Component: (await import("./pages/Employee")).Employee }),
      },
      { path: "/admin", element: <Navigate to="/admin/home" replace /> },
      {
        path: "/admin/:tab",
        lazy: async () => ({ Component: (await import("./pages/Admin")).Admin }),
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
];
