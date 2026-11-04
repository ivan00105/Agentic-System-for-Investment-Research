// Pick companies from SEC's ticker list as you type (WAI-ARIA combobox); picked ones show as removable chips.
import { useEffect, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { agentApi } from '../../api'
import type { CompanyMatch } from '../../api'
import { companyName } from './templates'

export function CompanyPicker({picked, onChange, label, max, hint}: {picked: CompanyMatch[]; onChange: (next: CompanyMatch[]) => void; label: string; max?: number; hint?: string}) {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<CompanyMatch[]>([])
  const [total, setTotal] = useState(0)
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const text = query.trim()
    if (!text) { setMatches([]); setTotal(0); return }
    const controller = new AbortController()
    const timer = setTimeout(() => agentApi.companies(text, controller.signal)
      .then(result => { setMatches(result.items); setTotal(result.total); setActive(0); setError('') })
      .catch(e => { if (!controller.signal.aborted) setError((e as Error).message) }), 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query])
  const full = max !== undefined && picked.length >= max
  const listed = open && matches.length > 0
  function pick(company: CompanyMatch) {
    if (!picked.some(p => p.cik === company.cik)) onChange([...picked, company])
    setQuery(''); setMatches([]); setOpen(false)
  }
  function key(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); setActive(a => Math.min(a + 1, matches.length - 1)) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (event.key === 'Enter' && listed && matches[active]) { event.preventDefault(); pick(matches[active]) }
    else if (event.key === 'Escape') setOpen(false)
    else if (event.key === 'Backspace' && !query && picked.length) onChange(picked.slice(0, -1))
  }
  return <div className="company-picker">
    <label htmlFor="company-search">{label}</label>
    {picked.length > 0 && <ul className="chips" aria-label="Picked companies">{picked.map(c => <li key={c.cik} className="chip">
      {companyName(c)} <span className="mono">{c.tickers[0]}</span>
      <button type="button" aria-label={`Remove ${companyName(c)}`} onClick={() => onChange(picked.filter(p => p.cik !== c.cik))}>×</button>
    </li>)}</ul>}
    <div className="combo">
      <input id="company-search" role="combobox" aria-expanded={listed} aria-controls="company-options" aria-autocomplete="list" autoComplete="off"
        aria-activedescendant={listed ? `company-option-${active}` : undefined} value={query} disabled={full}
        placeholder={full ? 'That is the most a comparison takes' : 'Type a name or ticker, e.g. Apple or MSFT'}
        onChange={e => { setQuery(e.target.value); setOpen(true) }} onKeyDown={key} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} />
      {listed && <ul id="company-options" role="listbox" className="combo-list" aria-label="Matching companies">
        {matches.map((c, i) => <li key={c.cik} id={`company-option-${i}`} role="option" aria-selected={i === active} onMouseDown={e => { e.preventDefault(); pick(c) }} onMouseEnter={() => setActive(i)}>
          <span>{companyName(c)}</span> <span className="mono">{c.tickers.join(', ')}</span>{c.exchanges.length > 0 && <small>{c.exchanges.join(', ')}</small>}
        </li>)}
        {total > matches.length && <li role="presentation" className="combo-more">{matches.length} of {total} matches. Type more to narrow them.</li>}
      </ul>}
    </div>
    {hint && <p className="form-note">{hint}</p>}
    {error && <p className="configuration-note">{error} You can still type company names into the question.</p>}
  </div>
}
