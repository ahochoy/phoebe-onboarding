import { Navigate, useParams, type RouteObject } from "react-router";
import { Landing } from "./pages/Landing";
import { Employee } from "./pages/Employee";
import { SessionGate } from "./session/SessionGate";

export const ADMIN_TABS = ["people", "documents", "tasks", "groups"] as const;
export type AdminTab = (typeof ADMIN_TABS)[number];

// Placeholders: later tasks replace these with the real pages.
function AdminPage() {
  const { tab } = useParams();
  if (!ADMIN_TABS.includes(tab as AdminTab)) return <Navigate to="/admin/people" replace />;
  return <h1 className="text-xl font-semibold">{`Admin: ${tab}`}</h1>;
}

export const routes: RouteObject[] = [
  { path: "/", element: <Landing /> },
  {
    element: <SessionGate />,
    children: [
      { path: "/employee", element: <Employee /> },
      { path: "/admin", element: <Navigate to="/admin/people" replace /> },
      { path: "/admin/:tab", element: <AdminPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
];
