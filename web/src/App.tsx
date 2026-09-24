import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Docs from './pages/public/Docs';
import Features from './pages/public/Features';
import Home from './pages/public/Home';
import OpenSource from './pages/public/OpenSource';
import Pricing from './pages/public/Pricing';
import Privacy from './pages/public/Privacy';
import Terms from './pages/public/Terms';
import HostedAppRedirect from './pages/auth/HostedAppRedirect';

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
        <Route path="/login" element={<HostedAppRedirect path="/login" />} />
        <Route path="/signup" element={<HostedAppRedirect path="/signup" />} />
        <Route path="/verify-email" element={<HostedAppRedirect path="/verify-email" />} />
        <Route path="/forgot-password" element={<HostedAppRedirect path="/forgot-password" />} />
        <Route path="/reset-password" element={<HostedAppRedirect path="/reset-password" />} />
        <Route path="/app/*" element={<HostedAppRedirect path="/app" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
