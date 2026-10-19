import { Link } from 'react-router-dom';

export default function PublicFooter() {
  return (
    <footer className="border-t px-6 py-10" style={{ borderColor: 'var(--border)' }}>
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row gap-5 justify-between md:items-center">
        <div>
          <div className="flex items-center gap-2 font-display text-sm mb-1" style={{ color: 'var(--foreground)' }}>
            <span className="w-5 h-5 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
            ResearchAgentLab
          </div>
          <p className="text-xs" style={{ color: 'var(--muted-foreground)' }}>Protocol before code. Evidence before claims.</p>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs" style={{ color: 'var(--muted-foreground)' }}>
          <Link to="/privacy">Privacy</Link>
          <Link to="/terms">Terms</Link>
          <a href="https://github.com/hncpyj/research-agent-lab" target="_blank" rel="noopener noreferrer">GitHub</a>
          <a href="https://github.com/hncpyj/research-agent-lab/issues" target="_blank" rel="noopener noreferrer">Issues</a>
        </div>
      </div>
    </footer>
  );
}
