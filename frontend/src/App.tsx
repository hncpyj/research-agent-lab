import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Docs from './pages/public/Docs';
import Features from './pages/public/Features';
import Home from './pages/public/Home';
import OpenSource from './pages/public/OpenSource';
import Pricing from './pages/public/Pricing';
import Privacy from './pages/public/Privacy';
import Terms from './pages/public/Terms';
import AccountFlow from './pages/auth/AccountFlow';
import { AuthProvider, ProtectedRoute } from './auth/AuthProvider';
import AppShell from './components/AppShell';
import Projects, { ProjectView } from './pages/app/Projects';
import Library from './pages/app/Library';
import { Account, Billing, Privacy as DataPrivacy, Usage } from './pages/app/AccountPages';
import ModelSettings, {LocalRunner} from './pages/app/ModelSettings';
import Dashboard from './pages/app/Dashboard';
import NewSession from './pages/app/NewSession';
import ResearchSession from './pages/app/ResearchSession';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
        {['login', 'signup', 'verify-email', 'forgot-password', 'reset-password'].map(path =>
          <Route key={path} path={`/${path}`} element={<AccountFlow key={path} />} />)}
        <Route element={<ProtectedRoute />}>
          <Route path="/app" element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="sessions/new" element={<NewSession />} />
            <Route path="sessions/:sessionId" element={<ResearchSession />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:projectId" element={<ProjectView />} />
            <Route path="projects/:projectId/sessions/new" element={<NewSession />} />
            <Route path="projects/:projectId/sessions/:sessionId" element={<ResearchSession />} />
            <Route path="library" element={<Library />} />
            <Route path="usage" element={<Usage />} />
            <Route path="settings/account" element={<Account />} />
            <Route path="settings/api" element={<ModelSettings />} />
            <Route path="settings/local-runner" element={<LocalRunner />} />
            <Route path="settings/billing" element={<Billing />} />
            <Route path="settings/privacy" element={<DataPrivacy />} />
            <Route path="*" element={<Navigate to="/app" replace />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
