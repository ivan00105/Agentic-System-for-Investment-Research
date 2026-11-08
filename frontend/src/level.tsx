// The detail level, one of the user's preferences: the same engine and reports, shown with more or less help.
import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

export type Level = 'beginner' | 'standard' | 'professional'
export const LEVELS: {id: Level; label: string; text: string}[] = [
  {id: 'beginner', label: 'Beginner', text: 'Plain words, finance terms explained, and a guided start.'},
  {id: 'standard', label: 'Standard', text: 'The report as written, with the extras folded away.'},
  {id: 'professional', label: 'Professional', text: 'Advanced options open: spec editing, raw figures, exports, agents and model.'},
]
const KEY = 'fieldnote-detail-level'
const Context = createContext<{level: Level; setLevel: (level: Level) => void}>({level: 'standard', setLevel: () => {}})

function saved(): Level {
  try { const value = localStorage.getItem(KEY); return LEVELS.some(l => l.id === value) ? value as Level : 'standard' }
  catch { return 'standard' } // storage blocked: the default still works
}

export function LevelProvider({children}: {children: ReactNode}) {
  const [level, set] = useState<Level>(saved)
  function setLevel(next: Level) { set(next); try { localStorage.setItem(KEY, next) } catch { /* not remembered */ } }
  return <Context.Provider value={{level, setLevel}}>{children}</Context.Provider>
}

export const useLevel = () => useContext(Context)

export function LevelPicker() {
  const {level, setLevel} = useLevel()
  return <span className="level-picker"><label htmlFor="detail-level">Detail level</label>
    <select id="detail-level" value={level} onChange={e => setLevel(e.target.value as Level)} aria-describedby="level-hint">
      {LEVELS.map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
    </select>
    <span id="level-hint" className="sr-only">{LEVELS.find(l => l.id === level)?.text}</span>
  </span>
}
