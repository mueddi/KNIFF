import { useEffect } from "react";
import { Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./lib/auth.jsx";
import { setUnauthorizedHandler } from "./lib/api.js";
import Landing from "./screens/Landing.jsx";
import Login from "./screens/Login.jsx";
import LoginVerify from "./screens/LoginVerify.jsx";
import AppShell from "./components/AppShell.jsx";
import Lernen from "./screens/Lernen.jsx";
import Pruefung from "./screens/Pruefung.jsx";
import Themen from "./screens/Themen.jsx";
import Bibliothek from "./screens/Bibliothek.jsx";
import Eltern from "./screens/Eltern.jsx";
import Preise from "./screens/Preise.jsx";
import Einstellungen from "./screens/Einstellungen.jsx";
import Kosten from "./screens/Kosten.jsx";
import Stoerungen from "./screens/Stoerungen.jsx";
import FeedbackAdmin from "./screens/FeedbackAdmin.jsx";
import Nutzer from "./screens/Nutzer.jsx";
import ParentDashboard from "./screens/ParentDashboard.jsx";
import { Impressum, Datenschutz, Agb } from "./screens/Rechtliches.jsx";

function Loader() {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100vh", color: "#9aa0ab", fontSize: 14 }}>
      lädt …
    </div>
  );
}

function RequireAdmin({ children }) {
  const { user } = useAuth();
  if (!user?.is_admin) return <Navigate to="/app/lernen" replace />;
  return children;
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Loader />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  // Rollen-Redirects: Eltern gehoeren nicht in die Schueler-Shell (und umgekehrt)
  if (user.role === "parent" && loc.pathname.startsWith("/app")) return <Navigate to="/eltern" replace />;
  if (user.role !== "parent" && loc.pathname.startsWith("/eltern")) return <Navigate to="/app/eltern" replace />;
  return children;
}

export default function App() {
  const { logout } = useAuth();
  const nav = useNavigate();

  // Supabase leitet nach dem Klick auf den Mail-Link auf seine «Site URL»
  // zurueck, wenn die uebergebene Adresse nicht in seiner Freigabeliste steht.
  // Das Token liegt dann im Fragment auf der STARTSEITE – wo es niemand
  // einloest und der Besucher einfach die Werbeseite sieht, obwohl der Link
  // gueltig war. Egal wo es ankommt: zur Verify-Seite weiterleiten und das
  // Fragment mitnehmen. Auch Fehler-Fragmente ("abgelaufener Link") gehoeren
  // dorthin, damit man eine Meldung sieht statt der Startseite.
  useEffect(() => {
    const hash = window.location.hash || "";
    if (!/[#&](access_token|error_description|error)=/.test(hash)) return;
    if (window.location.pathname === "/login/verify") return;
    nav(`/login/verify${hash}`, { replace: true });
  }, [nav]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout();
      // Nur von geschuetzten Seiten zum Login schicken – ein abgelaufenes Token
      // auf Landing/Impressum darf den Besucher nicht wegreissen.
      const path = window.location.pathname;
      if (path.startsWith("/app") || path.startsWith("/eltern")) {
        nav("/login", { replace: true });
      }
    });
  }, [logout, nav]);

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/login/verify" element={<LoginVerify />} />
      <Route path="/impressum" element={<Impressum />} />
      <Route path="/datenschutz" element={<Datenschutz />} />
      <Route path="/agb" element={<Agb />} />
      <Route
        path="/eltern"
        element={
          <RequireAuth>
            <ParentDashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/app"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="lernen" replace />} />
        <Route path="lernen" element={<Lernen />} />
        <Route path="lernen/:attemptId" element={<Lernen />} />
        <Route path="themen" element={<Themen />} />
        <Route path="themen/:topicId" element={<Themen />} />
        <Route path="pruefung/:examId" element={<Pruefung />} />
        <Route path="bibliothek" element={<Bibliothek />} />
        <Route path="eltern" element={<Eltern />} />
        <Route path="preise" element={<Preise />} />
        <Route path="einstellungen" element={<Einstellungen />} />
        <Route path="kosten" element={<RequireAdmin><Kosten /></RequireAdmin>} />
        <Route path="stoerungen" element={<RequireAdmin><Stoerungen /></RequireAdmin>} />
        <Route path="rueckmeldungen" element={<RequireAdmin><FeedbackAdmin /></RequireAdmin>} />
        <Route path="nutzer" element={<RequireAdmin><Nutzer /></RequireAdmin>} />
        <Route path="elternansicht" element={<RequireAdmin><ParentDashboard preview /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function NotFound() {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100vh", background: "#fbfbfd", padding: 24 }}>
      <div style={{ textAlign: "center", maxWidth: 400 }}>
        <div style={{ width: 64, height: 64, borderRadius: 18, background: "#eef0fe", color: "#4f46e5", fontSize: 28, display: "grid", placeItems: "center", margin: "0 auto 16px", fontWeight: 800 }}>404</div>
        <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>Diese Seite gibt es nicht</div>
        <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 20 }}>Vielleicht ein Tippfehler in der Adresse? Zurück geht's hier:</div>
        <a href="/" className="btn-primary" style={{ display: "inline-block", padding: "12px 20px", borderRadius: 12, fontSize: 14 }}>Zur Startseite</a>
      </div>
    </div>
  );
}
