import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import Home from './pages/public/Home';
import Pricing from './pages/public/Pricing';
import OpenSource from './pages/public/OpenSource';
import { appLink } from './appUrl';

/**
 * This site is the public one. The screens under src/pages/app and
 * src/pages/auth are design references with made-up numbers in them, so they
 * are deliberately not routed here: a visitor must never be shown a dashboard
 * of invented usage as though it were their own. Signing in, and everything
 * after it, happens in the application itself.
 */
function ToApp({ path = '' }: { path?: string }) {
  useEffect(() => {
    window.location.replace(appLink(path));
  }, [path]);
  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--background)' }}>
      <p className="font-display text-2xl font-light" style={{ color: 'var(--muted-foreground)' }}>
        Opening ResearchAgentLab…
      </p>
    </div>
  );
}

function Placeholder({ label }: { label: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--background)' }}>
      <p className="font-display text-2xl font-light" style={{ color: 'var(--muted-foreground)' }}>{label}</p>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/" element={<Home />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/open-source" element={<OpenSource />} />
        <Route path="/docs" element={<Placeholder label="Documentation" />} />
        <Route path="/privacy" element={<Placeholder label="Privacy Policy" />} />
        <Route path="/terms" element={<Placeholder label="Terms of Service" />} />

        {/* The application, wherever it is deployed */}
        <Route path="/login" element={<ToApp />} />
        <Route path="/signup" element={<ToApp />} />
        <Route path="/app/*" element={<ToApp />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
