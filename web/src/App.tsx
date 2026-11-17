import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { homeFor } from "./auth/session";
import { Admin } from "./pages/Admin";
import { Chat } from "./pages/Chat";
import { Login } from "./pages/Login";
import { Placeholder } from "./pages/Placeholder";
import { Styleguide } from "./pages/Styleguide";

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? homeFor(user.role) : "/login"} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/chat"
        element={
          <RequireAuth roles={["student"]}>
            <Chat />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth roles={["admin"]}>
            <Admin />
          </RequireAuth>
        }
      />
      <Route
        path="/account"
        element={
          <RequireAuth roles={["bank"]}>
            <Placeholder title="Bank account">
              The bank role uses the Banking API (tuition query and payment) directly; it has no web screen.
              The endpoints are listed in the API documentation at /api/v1/docs.
            </Placeholder>
          </RequireAuth>
        }
      />
      <Route path="/styleguide" element={<Styleguide />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
