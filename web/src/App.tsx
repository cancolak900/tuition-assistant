import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Styleguide } from "./pages/Styleguide";

// Screens (login, chat, admin) are added one by one; the style guide renders the Figma design system.
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/styleguide" element={<Styleguide />} />
        <Route path="*" element={<Navigate to="/styleguide" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
