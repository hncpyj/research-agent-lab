import { Link, useLocation } from 'react-router-dom';
import { useState } from 'react';
import { hostedAppUrl } from '../config';

const repositoryUrl = 'https://github.com/hncpyj/research-agent-lab';

const links = [
  { to: '/features', label: 'Architecture' },
  { to: '/docs', label: 'Run locally' },
  { to: '/source', label: 'Source' },
  { to: '/availability', label: 'Availability' },
];

export default function PublicNav() {
  const location = useLocation();
  const [open, setOpen] = useState(false);

  return (
    <>
    <a href="#main-content" className="public-skip-link">Skip to content</a>
    <nav aria-label="Main navigation" className="fixed top-0 left-0 right-0 z-50 border-b" style={{ background: 'rgba(247,248,252,0.94)', backdropFilter: 'blur(12px)', borderColor: 'var(--border)' }}>
      <div className="max-w-6xl mx-auto px-6 flex items-center justify-between h-14">
        <Link to="/" className="flex items-center gap-2 font-display font-medium text-sm" style={{ color: 'var(--foreground)' }}>
          <span className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
          ResearchAgentLab
        </Link>

        <div className="hidden md:flex items-center gap-6">
          {links.map(link => (
            <Link key={link.to} to={link.to} className="text-sm transition-colors" style={{ color: location.pathname === link.to ? 'var(--primary)' : 'var(--muted-foreground)' }}>
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden md:flex items-center gap-2">
          <a href={hostedAppUrl('/login')} className="text-sm px-3 py-1.5 rounded font-medium" style={{ color: 'var(--foreground)' }}>Sign in</a>
          <a href={hostedAppUrl('/signup')} className="text-sm px-3 py-1.5 rounded font-medium" style={{ color: 'var(--muted-foreground)' }}>Try beta</a>
          <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="text-sm px-4 py-2 rounded font-semibold inline-flex items-center gap-2" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .7A11.5 11.5 0 0 0 8.36 23c.58.1.79-.25.79-.56v-2.02c-3.22.7-3.9-1.37-3.9-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.04 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.29-5.27-5.72 0-1.26.45-2.3 1.19-3.1-.12-.3-.52-1.48.11-3.07 0 0 .97-.31 3.16 1.18a10.9 10.9 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.59.23 2.77.11 3.06.74.82 1.19 1.85 1.19 3.11 0 4.45-2.71 5.43-5.29 5.72.42.36.79 1.06.79 2.14v3.18c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" /></svg>
            GitHub
          </a>
        </div>

        <button type="button" className="md:hidden p-2" onClick={() => setOpen(value => !value)} aria-label={open ? 'Close navigation menu' : 'Open navigation menu'} aria-expanded={open} aria-controls="mobile-navigation" style={{ color: 'var(--muted-foreground)' }}>
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
            {open
              ? <path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" />
              : <path fillRule="evenodd" clipRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />}
          </svg>
        </button>
      </div>

      {open && (
        <div id="mobile-navigation" className="md:hidden border-t px-6 py-4 flex flex-col gap-4" style={{ borderColor: 'var(--border)', background: 'var(--background)' }}>
          {links.map(link => (
            <Link key={link.to} to={link.to} className="text-sm" style={{ color: 'var(--muted-foreground)' }} onClick={() => setOpen(false)}>{link.label}</Link>
          ))}
          <a href={hostedAppUrl('/login')} className="text-sm px-4 py-2 rounded font-medium text-center border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Sign in</a>
          <a href={hostedAppUrl('/signup')} className="text-sm px-4 py-2 rounded font-medium text-center border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Try beta</a>
          <a href={repositoryUrl} target="_blank" rel="noopener noreferrer" className="text-sm px-4 py-2 rounded font-semibold text-center" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>View GitHub repository</a>
        </div>
      )}
    </nav>
    </>
  );
}
