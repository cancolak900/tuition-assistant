import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import type { Role } from "../api/auth";
import { useAuth } from "./AuthContext";
import { homeFor } from "./session";

/** Sends signed-out users to /login (and back afterwards) and users with another role to their own home. */
export function RequireAuth({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}
