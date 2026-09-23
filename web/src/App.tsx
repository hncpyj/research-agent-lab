import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Docs from './pages/public/Docs';
import Features from './pages/public/Features';
import Home from './pages/public/Home';
import OpenSource from './pages/public/OpenSource';
import Pricing from './pages/public/Pricing';
import Privacy from './pages/public/Privacy';
import Terms from './pages/public/Terms';

/**
 * This deployment is intentionally static and informational. The design-only
 * account and application screens under src/pages/auth and src/pages/app are
 * not imported or routed into the public bundle.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/features" element={<Features />} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/source" element={<OpenSource />} />
        <Route path="/open-source" element={<Navigate to="/source" replace />} />
        <Route path="/availability" element={<Pricing />} />
        <Route path="/pricing" element={<Navigate to="/availability" replace />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/login" element={<Navigate to="/availability" replace />} />
        <Route path="/signup" element={<Navigate to="/availability" replace />} />
        <Route path="/app/*" element={<Navigate to="/availability" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
