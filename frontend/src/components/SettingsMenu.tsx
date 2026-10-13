import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { DatabaseInfo } from '../api/types'
import type { ThemePreference } from '../hooks/useTheme'
import { CheckIcon, ChevronUpDownIcon, DatabaseIcon, GithubIcon, HelpIcon, MonitorIcon, MoonIcon, PlugIcon, SunIcon, TableIcon } from './icons'

const REPO_URL = 'https://github.com/Parth-Vasave/frontiersql'

const STATUS_TEXT: Record<DatabaseInfo['status'], string> = {
  ready: 'read-only',
  rejected: 'not read-only — disabled',
  unavailable: 'unavailable',
}

interface SettingsMenuProps {
  databases: DatabaseInfo[]
  activeId: string | null
  onSelectDatabase: (id: string) => void
  onConnect: () => void
  onSchema: () => void
  onHelp: () => void
  theme: ThemePreference
  onTheme: (theme: ThemePreference) => void
}

/** The bottom-left button: the connected database at a glance, and everything you can set. */
export function SettingsMenu({ databases, activeId, onSelectDatabase, onConnect, onSchema, onHelp, theme, onTheme }: SettingsMenuProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const active = databases.find((d) => d.id === activeId)

  useEffect(() => {
    if (!open) return
    menu.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus()
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  function close() {
    setOpen(false)
    trigger.current?.focus()
  }

  function run(action: () => void) {
    setOpen(false)
    action()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const items = Array.from(menu.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? [])
    const index = items.indexOf(document.activeElement as HTMLElement)
    const next =
      event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }

  return (
    <div ref={root} className="relative">
      {open && (
        <div
          ref={menu}
          role="menu"
          aria-label="Settings"
          onKeyDown={handleKeyDown}
          className="rise-in absolute right-0 bottom-full left-0 z-30 mb-2 max-h-[70dvh] overflow-y-auto rounded-2xl border border-line bg-surface p-1.5 text-[14px] shadow-[var(--shadow-menu)]"
        >
          <GroupLabel>Database</GroupLabel>
          {databases.length === 0 && <p className="px-3 py-2 text-[13.5px] text-ink-faint">No database configured</p>}
          {databases.map((db) => (
            <button
              key={db.id}
              type="button"
              role="menuitemradio"
              aria-checked={db.id === activeId}
              onClick={() => run(() => onSelectDatabase(db.id))}
              className={ITEM}
            >
              <StatusDot status={db.status} />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{db.name}</span>
                <span className={`block text-[12.5px] ${db.status === 'rejected' ? 'text-accent' : 'text-ink-faint'}`}>
                  {db.dialect} · {STATUS_TEXT[db.status]} · sampling {db.sampling}
                </span>
              </span>
              {db.id === activeId && <CheckIcon size={16} className="shrink-0 text-ink" />}
            </button>
          ))}
          <button type="button" role="menuitem" onClick={() => run(onConnect)} className={ITEM}>
            <PlugIcon size={17} className="text-ink-dim" />
            Connect a database…
          </button>
          <button type="button" role="menuitem" onClick={() => run(onSchema)} disabled={!active} className={ITEM}>
            <TableIcon size={17} className="text-ink-dim" />
            Browse schema
          </button>

          <Separator />
          <GroupLabel>Theme</GroupLabel>
          <div className="grid grid-cols-3 gap-1 px-1.5 pb-1" role="group" aria-label="Theme">
            {(
              [
                ['light', 'Light', SunIcon],
                ['dark', 'Dark', MoonIcon],
                ['system', 'System', MonitorIcon],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="menuitemradio"
                aria-checked={theme === value}
                onClick={() => onTheme(value)}
                className={`flex flex-col items-center gap-1 rounded-xl py-2 text-[12.5px] transition-colors ${theme === value ? 'bg-raised text-ink' : 'text-ink-dim hover:bg-raised/60 hover:text-ink'}`}
              >
                <Icon size={17} />
                {label}
              </button>
            ))}
          </div>

          <Separator />
          <button type="button" role="menuitem" onClick={() => run(onHelp)} className={ITEM}>
            <HelpIcon size={17} className="text-ink-dim" />
            How it works
          </button>
          <a role="menuitem" href={REPO_URL} target="_blank" rel="noreferrer" className={ITEM} onClick={() => setOpen(false)}>
            <GithubIcon size={17} className="text-ink-dim" />
            Source on GitHub
          </a>
        </div>
      )}

      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Settings and database"
        className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-raised"
      >
        <span className="relative flex size-8 shrink-0 items-center justify-center rounded-full bg-raised text-ink-dim">
          <DatabaseIcon size={17} />
          {active && (
            <span className="absolute -right-0.5 -bottom-0.5 rounded-full border-2 border-sidebar">
              <StatusDot status={active.status} />
            </span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium">{active?.name ?? 'No database'}</span>
          <span className={`block truncate text-[12.5px] ${active?.status === 'rejected' ? 'text-accent' : 'text-ink-faint'}`}>
            {active ? `${active.dialect} · ${STATUS_TEXT[active.status]}` : 'Connect one to start'}
          </span>
        </span>
        <ChevronUpDownIcon size={16} className="shrink-0 text-ink-faint" />
      </button>
    </div>
  )
}

const ITEM =
  'flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-ink transition-colors hover:bg-raised focus-visible:bg-raised focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40'

function GroupLabel({ children }: { children: ReactNode }) {
  return <p className="px-3 pt-1.5 pb-1 text-[12px] font-medium text-ink-faint">{children}</p>
}

function Separator() {
  return <div className="mx-2 my-1.5 border-t border-line" role="separator" />
}

export function StatusDot({ status }: { status: DatabaseInfo['status'] }) {
  // Ready is the good case (green); a writable account is the one alert (amber); unavailable is grey.
  const color = status === 'ready' ? 'bg-ok' : status === 'rejected' ? 'bg-accent' : 'bg-ink-faint'
  return <span className={`block size-2 shrink-0 rounded-full ${color}`} aria-hidden="true" />
}
