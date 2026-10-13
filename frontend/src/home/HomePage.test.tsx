import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { BLOCKED_STATEMENTS } from './evaluation'
import { CHAT_URL, HomePage } from './HomePage'
import { RECORDED_ANSWER } from './recordedAnswer'

describe('HomePage', () => {
  it('sends the primary action to the chat app and links the source', () => {
    render(<HomePage />)
    expect(CHAT_URL).toBe('/chat/')
    for (const link of screen.getAllByRole('link', { name: 'Try the demo' })) {
      expect(link).toHaveAttribute('href', '/chat/')
    }
    expect(screen.getAllByRole('link', { name: /View on GitHub/ })[0]).toHaveAttribute(
      'href',
      'https://github.com/Parth-Vasave/frontiersql',
    )
  })

  it('shows the recorded answer finished when the replay cannot animate', () => {
    // jsdom has no IntersectionObserver, which is the same path as reduced motion.
    render(<HomePage />)
    const figure = screen.getByRole('figure')
    expect(within(figure).getByText(/^The five highest/)).toBeVisible()
    expect(within(figure).getByRole('button', { name: /Validated read-only SQL/ })).toHaveAttribute('aria-expanded', 'false')
    expect(within(figure).getByText(/recorded 2026-10-05 with openai\/gpt-oss-120b/)).toBeInTheDocument()
  })

  it('opens the same answer’s verification in the how-it-works section', () => {
    render(<HomePage />)
    const section = screen.getByRole('region', { name: 'Every answer shows its work' })
    expect(within(section).getByRole('button', { name: /Validated read-only SQL/ })).toHaveAttribute('aria-expanded', 'true')
    expect(within(section).getByText(RECORDED_ANSWER.sql!)).toBeInTheDocument()
  })

  it('lists the blocked statements, expanding to all of them', async () => {
    const user = userEvent.setup()
    render(<HomePage />)
    const section = screen.getByRole('region', { name: 'What the validator refuses' })
    expect(within(section).getByText('28 of 28 statements blocked')).toBeInTheDocument()
    expect(within(section).getAllByRole('row')).toHaveLength(1 + 6)

    await user.click(within(section).getByRole('button', { name: 'Show all 28' }))
    expect(within(section).getAllByRole('row')).toHaveLength(1 + BLOCKED_STATEMENTS.length)
    expect(within(section).getByText('SET statement_timeout = 0')).toBeInTheDocument()
  })

  it('shows the recorded evaluation with its run and the misses', () => {
    render(<HomePage />)
    const section = screen.getByRole('region', { name: 'Evaluation, as recorded' })
    const row = (label: string) => within(section).getByRole('rowheader', { name: label }).closest('tr')
    expect(row('Answer accuracy')).toHaveTextContent('74/7895%')
    expect(row('Clarification accuracy (ambiguous questions)')).toHaveTextContent('3/560%')
    expect(row('Safety violations')).toHaveTextContent('0 of 78')
    expect(within(section).getByText('20261004-061307-questions')).toBeInTheDocument()
    for (const id of ['Q028', 'Q052', 'Q056', 'Q058']) expect(within(section).getByText(id)).toBeInTheDocument()
  })

  it('switches the theme from the footer', async () => {
    const user = userEvent.setup()
    render(<HomePage />)
    await user.click(screen.getByRole('radio', { name: 'Dark' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
  })
})
