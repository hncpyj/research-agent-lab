export default function DataView({ value }: { value: unknown }) {
  if (value == null) return <span className="muted">—</span>;
  if (typeof value === 'boolean') return <span>{value ? 'Yes' : 'No'}</span>;
  if (Array.isArray(value)) return value.length
    ? <div className="stack">{value.map((item, i) => <div className="panel" key={i}><DataView value={item} /></div>)}</div>
    : <span className="muted">No records.</span>;
  if (typeof value === 'object') return <dl className="data-view">{Object.entries(value).map(([key, item]) =>
    <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd><DataView value={item} /></dd></div>)}</dl>;
  return <span className="preserve">{String(value)}</span>;
}
