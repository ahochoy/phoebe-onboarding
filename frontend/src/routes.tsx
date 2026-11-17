import { Navigate, type RouteObject } from "react-router";
import { Landing } from "./pages/Landing";
import { Admin } from "./pages/Admin";
import { Employee } from "./pages/Employee";
import { SessionGate } from "./session/SessionGate";

export const routes: RouteObject[] = [
  { path: "/", element: <Landing /> },
  {
    element: <SessionGate />,
    children: [
      { path: "/employee", element: <Employee /> },
      { path: "/admin", element: <Navigate to="/admin/home" replace /> },
      { path: "/admin/:tab", element: <Admin /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
];
