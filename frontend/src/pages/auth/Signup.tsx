import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';

export default function Signup() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handle = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/onboarding');
  };

  return (
    <div className="public-light min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <Link to="/" className="flex items-center gap-2 font-display font-medium text-sm justify-center mb-8" style={{ color: 'var(--foreground)' }}>
          <span className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold font-mono" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>R</span>
          ResearchAgentLab
        </Link>
        <div className="p-8 rounded-lg border" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
          <h1 className="font-display text-2xl font-light mb-2" style={{ color: 'var(--foreground)' }}>Create account</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--muted-foreground)' }}>Start researching free — no card required.</p>
          <form onSubmit={handle} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
                className="w-full px-3 py-2.5 rounded border text-sm outline-none"
                style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--foreground)' }}
                placeholder="you@university.edu"/>
            </div>
            <div>
              <label className="block text-xs mb-1.5" style={{ color: 'var(--muted-foreground)' }}>Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
                className="w-full px-3 py-2.5 rounded border text-sm outline-none"
                style={{ background: 'var(--secondary)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
            </div>
            <button type="submit" className="w-full py-2.5 rounded font-medium text-sm mt-1" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
              Create account
            </button>
          </form>
          <p className="text-xs text-center mt-4" style={{ color: 'var(--muted-foreground)' }}>
            By creating an account you agree to our <Link to="/terms" style={{ color: 'var(--primary)' }}>Terms</Link> and <Link to="/privacy" style={{ color: 'var(--primary)' }}>Privacy Policy</Link>.
          </p>
        </div>
        <p className="text-center text-sm mt-6" style={{ color: 'var(--muted-foreground)' }}>
          Already have an account? <Link to="/login" style={{ color: 'var(--primary)' }}>Sign in</Link>
        </p>
      </div>
    </div>
  );
}
