import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';

const navItems = [
  { to: '/app', label: 'Home', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1.5l6 5.5v7a.5.5 0 01-.5.5h-3.5V10H6v4.5H2.5A.5.5 0 012 14V7l6-5.5z"/></svg>
  )},
  { to: '/app/projects', label: 'Projects', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M1.5 2A1.5 1.5 0 000 3.5v9A1.5 1.5 0 001.5 14h13a1.5 1.5 0 001.5-1.5v-7A1.5 1.5 0 0014.5 4H8L6.5 2h-5z"/></svg>
  )},
  { to: '/app/library', label: 'Library', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M1 2.5A1.5 1.5 0 012.5 1h3A1.5 1.5 0 017 2.5v3A1.5 1.5 0 015.5 7h-3A1.5 1.5 0 011 5.5v-3zm8 0A1.5 1.5 0 0110.5 1h3A1.5 1.5 0 0115 2.5v3A1.5 1.5 0 0113.5 7h-3A1.5 1.5 0 019 5.5v-3zm-8 8A1.5 1.5 0 012.5 9h3A1.5 1.5 0 017 10.5v3A1.5 1.5 0 015.5 15h-3A1.5 1.5 0 011 13.5v-3zm8 0A1.5 1.5 0 0110.5 9h3A1.5 1.5 0 0115 10.5v3A1.5 1.5 0 0113.5 15h-3A1.5 1.5 0 019 13.5v-3z"/></svg>
  )},
  { to: '/app/usage', label: 'Usage', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1a7 7 0 100 14A7 7 0 008 1zM0 8a8 8 0 1116 0A8 8 0 010 8zm7.5-3.5a.5.5 0 011 0V8a.5.5 0 01-.146.354l-2 2a.5.5 0 01-.708-.708L7.5 7.793V4.5z"/></svg>
  )},
];

const settingsItems = [
  { to: '/app/settings/account', label: 'Account' },
  { to: '/app/settings/api', label: 'API Providers' },
  { to: '/app/settings/billing', label: 'Billing' },
  { to: '/app/settings/local-runner', label: 'Local Runner' },
  { to: '/app/settings/privacy', label: 'Privacy' },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [settingsOpen, setSettingsOpen] = useState(location.pathname.includes('/settings'));

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--background)' }}>
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 flex flex-col border-r" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <div className="h-14 flex items-center px-4 border-b" style={{ borderColor: 'var(--border)' }}>
          <Link to="/" className="flex items-center gap-2 font-display font-medium text-sm" style={{ color: 'var(--foreground)' }}>
            <span className="w-5 h-5 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
            ResearchAgentLab
          </Link>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-1">
          {navItems.map(item => {
            const active = item.to === '/app' ? location.pathname === '/app' : location.pathname.startsWith(item.to);
            return (
              <Link key={item.to} to={item.to} className="flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors"
                style={{ background: active ? 'var(--secondary)' : 'transparent', color: active ? 'var(--foreground)' : 'var(--muted-foreground)' }}>
                {item.icon}
                {item.label}
              </Link>
            );
          })}

          <div className="mt-4">
            <button onClick={() => setSettingsOpen(v => !v)} className="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors"
              style={{ color: location.pathname.includes('/settings') ? 'var(--foreground)' : 'var(--muted-foreground)' }}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 4.754a3.246 3.246 0 100 6.492 3.246 3.246 0 000-6.492zM5.754 8a2.246 2.246 0 114.492 0 2.246 2.246 0 01-4.492 0z"/><path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 01-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 01-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 01.52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292-.159a.873.873 0 011.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 011.255-.52l.292.16c1.64.893 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 01.52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 01-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a.873.873 0 01-1.255-.52l-.094-.319z"/></svg>
              Settings
              <svg className="ml-auto" width="12" height="12" viewBox="0 0 12 12" fill="currentColor" style={{ transform: settingsOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
                <path d="M2 4l4 4 4-4"/>
              </svg>
            </button>
            {settingsOpen && (
              <div className="ml-3 mt-1 flex flex-col gap-0.5">
                {settingsItems.map(item => {
                  const active = location.pathname === item.to;
                  return (
                    <Link key={item.to} to={item.to} className="px-3 py-1.5 rounded text-xs transition-colors"
                      style={{ color: active ? 'var(--foreground)' : 'var(--muted-foreground)', background: active ? 'var(--secondary)' : 'transparent' }}>
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </nav>

        <div className="px-3 py-3 border-t" style={{ borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-2.5 px-3 py-2 rounded text-sm" style={{ color: 'var(--muted-foreground)' }}>
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>A</div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate" style={{ color: 'var(--foreground)' }}>alice@uni.ac.uk</div>
              <div className="text-xs" style={{ color: 'var(--muted-foreground)' }}>Free plan</div>
            </div>
          </div>
          <button onClick={() => navigate('/')} className="w-full text-left px-3 py-1.5 rounded text-xs mt-1 transition-colors" style={{ color: 'var(--muted-foreground)' }}>
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
