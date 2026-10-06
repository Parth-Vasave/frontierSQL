import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { ApiError, type DatabaseInfo } from '../api/types'
import { ConnectDatabaseForm } from './ConnectDatabaseForm'

vi.mock('../api/client')

describe('ConnectDatabaseForm', () => {
  it('submits the trimmed name, url and sampling mode', async () => {
    const added: DatabaseInfo = {
      id: 'shop',
      name: 'My shop database',
      dialect: 'postgresql',
      source: 'ui',
      sampling: 'off',
      status: 'ready',
      issues: [],
      allowed_columns: [],
    }
    vi.mocked(client.addDatabase).mockResolvedValue(added)
    const onConnected = vi.fn()
    render(<ConnectDatabaseForm onConnected={onConnected} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/name/i), '  My shop database  ')
    await userEvent.type(screen.getByLabelText(/connection url/i), '  postgresql://user:pw@host:5432/shop  ')
    await userEvent.selectOptions(screen.getByLabelText(/sampling/i), 'off')
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }))

    expect(client.addDatabase).toHaveBeenCalledWith({
      name: 'My shop database',
      url: 'postgresql://user:pw@host:5432/shop',
      sampling: 'off',
    })
    await vi.waitFor(() => expect(onConnected).toHaveBeenCalledWith(added))
  })

  it('shows the server error, including any listed issues, and lets the user retry', async () => {
    vi.mocked(client.addDatabase).mockRejectedValue(
      new ApiError('Database not added: it is rejected. (account can create roles; account can create temporary tables)', 422),
    )
    render(<ConnectDatabaseForm onConnected={vi.fn()} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/name/i), 'writable db')
    await userEvent.type(screen.getByLabelText(/connection url/i), 'postgresql://owner:pw@host:5432/db')
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }))

    expect(await screen.findByText(/account can create roles/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^connect$/i })).not.toBeDisabled()
  })

  it('disables submit and shows a hint for a malformed url', async () => {
    render(<ConnectDatabaseForm onConnected={vi.fn()} onCancel={vi.fn()} />)

    await userEvent.type(screen.getByLabelText(/name/i), 'my db')
    await userEvent.type(screen.getByLabelText(/connection url/i), 'not-a-url')

    expect(screen.getByText(/expected scheme:\/\/user:password@host:port\/database/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^connect$/i })).toBeDisabled()
    expect(client.addDatabase).not.toHaveBeenCalled()
  })

  it('calls onCancel without submitting', async () => {
    const onCancel = vi.fn()
    render(<ConnectDatabaseForm onConnected={vi.fn()} onCancel={onCancel} />)

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(onCancel).toHaveBeenCalled()
    expect(client.addDatabase).not.toHaveBeenCalled()
  })
})
