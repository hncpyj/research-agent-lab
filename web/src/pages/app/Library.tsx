import { useState } from 'react';
import AppShell from '../../components/AppShell';

const papers = [
  { id: 1, title: 'Chain-of-Thought Prompting Elicits Reasoning in Large Language Models', authors: 'Wei et al.', year: 2022, venue: 'NeurIPS', status: 'Included', relevance: 'High', doi: '10.48550/arXiv.2201.11903', abstract: 'We explore how generating a chain of thought — a series of intermediate reasoning steps — significantly improves the ability of large language models to perform complex reasoning.' },
  { id: 2, title: 'Large Language Models are Zero-Shot Reasoners', authors: 'Kojima et al.', year: 2022, venue: 'NeurIPS', status: 'Included', relevance: 'High', doi: '10.48550/arXiv.2205.11916', abstract: 'We demonstrate that LLMs are decent zero-shot reasoners by simply adding "Let\'s think step by step" before each answer.' },
  { id: 3, title: 'Measuring Mathematical Problem Solving With the MATH Dataset', authors: 'Hendrycks et al.', year: 2021, venue: 'NeurIPS', status: 'Screened', relevance: 'Medium', doi: '10.48550/arXiv.2103.03874', abstract: 'We introduce MATH, a new dataset of 12,500 challenging competition mathematics problems.' },
  { id: 4, title: 'Neural Machine Translation by Jointly Learning to Align and Translate', authors: 'Bahdanau et al.', year: 2015, venue: 'ICLR', status: 'Excluded', relevance: 'Low', doi: '10.48550/arXiv.1409.0473', abstract: 'Off-topic: focuses on attention mechanisms in translation, not reasoning benchmarks.' },
  { id: 5, title: 'Self-Consistency Improves Chain of Thought Reasoning in Language Models', authors: 'Wang et al.', year: 2023, venue: 'ICLR', status: 'Included', relevance: 'High', doi: '10.48550/arXiv.2203.11171', abstract: 'We introduce self-consistency, a decoding strategy that samples diverse reasoning paths and marginalizes out the final answer.' },
];

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  Included: { bg: 'rgba(110,200,122,0.1)', color: '#6ec87a' },
  Excluded: { bg: 'rgba(239,68,68,0.1)', color: '#ef4444' },
  Screened: { bg: 'rgba(240,160,48,0.1)', color: 'var(--accent)' },
  Discovered: { bg: 'rgba(0,200,168,0.1)', color: 'var(--primary)' },
};

export default function Library() {
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('All');
  const [selected, setSelected] = useState<number | null>(null);

  const filtered = papers.filter(p =>
    (filterStatus === 'All' || p.status === filterStatus) &&
    (p.title.toLowerCase().includes(search.toLowerCase()) || p.authors.toLowerCase().includes(search.toLowerCase()))
  );

  const paper = papers.find(p => p.id === selected);

  return (
    <AppShell>
      <div className="p-8 max-w-6xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="font-display text-3xl font-light mb-1" style={{ color: 'var(--foreground)' }}>Paper Library</h1>
            <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>{papers.length} papers across all projects</p>
          </div>
        </div>

        <div className="flex gap-3 mb-6">
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search title or author..."
            className="flex-1 px-3 py-2 rounded border text-sm outline-none"
            style={{ background: 'var(--card)', borderColor: 'var(--border)', color: 'var(--foreground)' }}/>
          <div className="flex gap-2">
            {['All', 'Included', 'Screened', 'Excluded'].map(s => (
              <button key={s} onClick={() => setFilterStatus(s)} className="px-3 py-2 rounded text-xs border transition-colors"
                style={{ background: filterStatus === s ? 'var(--primary)' : 'var(--card)', color: filterStatus === s ? 'var(--primary-foreground)' : 'var(--muted-foreground)', borderColor: filterStatus === s ? 'transparent' : 'var(--border)' }}>
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-4">
          <div className="flex-1 flex flex-col gap-2">
            {filtered.map(p => (
              <button key={p.id} onClick={() => setSelected(p.id)} className="p-4 rounded-lg border text-left transition-all"
                style={{ background: selected === p.id ? 'var(--secondary)' : 'var(--card)', borderColor: selected === p.id ? 'var(--primary)' : 'var(--border)' }}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium mb-1" style={{ color: 'var(--foreground)' }}>{p.title}</p>
                    <p className="text-xs" style={{ color: 'var(--muted-foreground)' }}>{p.authors} · {p.year} · {p.venue}</p>
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded font-mono flex-shrink-0" style={{ background: STATUS_COLORS[p.status]?.bg, color: STATUS_COLORS[p.status]?.color }}>{p.status}</span>
                </div>
              </button>
            ))}
          </div>

          {paper && (
            <div className="w-80 flex-shrink-0 p-6 rounded-lg border self-start sticky top-0" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}>
              <div className="flex justify-between mb-3">
                <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ background: STATUS_COLORS[paper.status]?.bg, color: STATUS_COLORS[paper.status]?.color }}>{paper.status}</span>
                <button onClick={() => setSelected(null)} className="text-xs" style={{ color: 'var(--muted-foreground)' }}>✕</button>
              </div>
              <h2 className="text-sm font-medium mb-2" style={{ color: 'var(--foreground)' }}>{paper.title}</h2>
              <p className="text-xs mb-4" style={{ color: 'var(--muted-foreground)' }}>{paper.authors} · {paper.year} · {paper.venue}</p>
              <p className="text-xs mb-4 leading-relaxed" style={{ color: 'var(--muted-foreground)' }}>{paper.abstract}</p>
              <div className="text-xs font-mono mb-4 p-2 rounded border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)', background: 'var(--secondary)' }}>
                DOI: {paper.doi}
              </div>
              <div className="flex flex-col gap-2">
                {paper.status !== 'Included' && <button className="w-full py-2 rounded text-xs font-medium" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>Include</button>}
                {paper.status !== 'Excluded' && <button className="w-full py-2 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--muted-foreground)' }}>Exclude</button>}
                <button className="w-full py-2 rounded text-xs border" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Add Note</button>
                <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noopener" className="w-full py-2 rounded text-xs border text-center block" style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}>Open Source</a>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
