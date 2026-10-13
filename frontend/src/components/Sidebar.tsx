import { useState, type ReactNode } from 'react'
import { groupChatsByDate } from '../lib/chats'
import { NewChatIcon, SidebarIcon, TrashIcon } from './icons'

export interface ChatSummary {
  id: string
  title: string
  updatedAt: number
  running: boolean
}

interface SidebarProps {
  chats: ChatSummary[]
  currentId: string | null
  onSelect: (id: string) => void
  onNewChat: () => void
  onDelete: (id: string) => void
  onClose: () => void
  closeLabel: string
  footer: ReactNode
}

export function Sidebar({ chats, currentId, onSelect, onNewChat, onDelete, onClose, closeLabel, footer }: SidebarProps) {
  const groups = groupChatsByDate(chats)

  return (
    <nav aria-label="Chats" className="flex h-full w-[17rem] flex-col bg-sidebar">
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <a href={import.meta.env.BASE_URL} className="flex items-center gap-2.5 rounded-lg px-1.5 py-1" title="Project home">
          <span className="text-[15px] font-semibold tracking-tight">FrontierSQL</span>
        </a>
        <button
          type="button"
          onClick={onClose}
          aria-label={closeLabel}
          className="rounded-lg p-2 text-ink-faint transition-colors hover:bg-raised hover:text-ink"
        >
          <SidebarIcon />
        </button>
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={onNewChat}
          className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-[14px] font-medium transition-colors hover:bg-raised"
        >
          <NewChatIcon size={18} className="text-ink-dim" />
          New chat
        </button>
      </div>

      <div className="mt-3 flex-1 overflow-y-auto px-3 pb-3">
        {groups.length === 0 && (
          <p className="px-2.5 py-2 text-[13.5px] leading-relaxed text-ink-faint">Your chats will appear here. They're saved in this browser only.</p>
        )}
        {groups.map((group) => (
          <section key={group.label} className="mb-4">
            <h2 className="px-2.5 pb-1 text-[12px] font-medium text-ink-faint">{group.label}</h2>
            <ul>
              {group.chats.map((chat) => (
                <ChatRow
                  key={chat.id}
                  chat={chat}
                  current={chat.id === currentId}
                  onSelect={() => onSelect(chat.id)}
                  onDelete={() => onDelete(chat.id)}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="border-t border-line p-2">{footer}</div>
    </nav>
  )
}

function ChatRow({ chat, current, onSelect, onDelete }: { chat: ChatSummary; current: boolean; onSelect: () => void; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false)

  return (
    <li
      className={`group relative flex items-center rounded-xl transition-colors ${current ? 'bg-raised' : 'hover:bg-raised/60'}`}
      onMouseLeave={() => setConfirming(false)}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-current={current ? 'page' : undefined}
        className="min-w-0 flex-1 truncate rounded-xl py-2 pr-9 pl-2.5 text-left text-[14px] text-ink"
      >
        {chat.running && <span className="pulse-dot mr-2 inline-block size-1.5 rounded-full bg-ink-dim align-middle" aria-label="running" />}
        {chat.title}
      </button>
      {confirming ? (
        <span className="absolute right-1 flex items-center gap-1 rounded-lg bg-surface pl-1 shadow-[var(--shadow-menu)]">
          <button
            type="button"
            onClick={onDelete}
            onBlur={() => setConfirming(false)}
            autoFocus
            className="rounded-lg px-2 py-1 text-[13px] font-medium text-accent hover:bg-accent-soft"
          >
            Delete
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`Delete chat: ${chat.title}`}
          className={`absolute right-1 rounded-lg p-1.5 text-ink-faint transition-opacity hover:text-ink focus-visible:opacity-100 ${current ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} max-md:opacity-100`}
        >
          <TrashIcon size={16} />
        </button>
      )}
    </li>
  )
}
