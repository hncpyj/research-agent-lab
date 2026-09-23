import { Link, useLocation } from 'react-router-dom';
import { useState } from 'react';

export default function PublicNav() {
  const location = useLocation();
  const [open, setOpen] = useState(false);

  const links = [
    { to: '/features', label: 'Features' },
    { to: '/pricing', label: 'Pricing' },
    { to: '/open-source', label: 'Open Source' },
    { to: '/docs', label: 'Docs' },
  ];

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b" style={{ background: 'rgba(247,248,252,0.92)', backdropFilter: 'blur(12px)', borderColor: 'var(--border)' }}>
      <div className="max-w-6xl mx-auto px-6 flex items-center justify-between h-14">
        <Link to="/" className="flex items-center gap-2 font-display font-medium text-sm" style={{ color: 'var(--foreground)' }}>
          <span className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
          ResearchAgentLab
        </Link>

        <div className="hidden md:flex items-center gap-6">
          {links.map(l => (
            <Link key={l.to} to={l.to} className="text-sm transition-colors" style={{ color: location.pathname === l.to ? 'var(--primary)' : 'var(--muted-foreground)' }}>
              {l.label}
            </Link>
          ))}
        </div>

        <div className="hidden md:flex items-center gap-3">
          <Link to="/login" className="text-sm px-4 py-1.5 rounded transition-colors" style={{ color: 'var(--muted-foreground)' }}>
            Sign In
          </Link>
          <Link to="/signup" className="text-sm px-4 py-1.5 rounded font-medium transition-colors" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            Start free
          </Link>
        </div>

        <button className="md:hidden p-2" onClick={() => setOpen(!open)} style={{ color: 'var(--muted-foreground)' }}>
          <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
            {open
              ? <path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" />
              : <path fillRule="evenodd" clipRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />}
          </svg>
        </button>
      </div>

      {open && (
        <div className="md:hidden border-t px-6 py-4 flex flex-col gap-4" style={{ borderColor: 'var(--border)', background: 'var(--background)' }}>
          {links.map(l => <Link key={l.to} to={l.to} className="text-sm" style={{ color: 'var(--muted-foreground)' }} onClick={() => setOpen(false)}>{l.label}</Link>)}
          <div className="flex gap-3 pt-2">
            <Link to="/login" className="text-sm px-4 py-1.5 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }} onClick={() => setOpen(false)}>Sign In</Link>
            <Link to="/signup" className="text-sm px-4 py-1.5 rounded font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }} onClick={() => setOpen(false)}>Start free</Link>
          </div>
        </div>
      )}
    </nav>
  );
}
