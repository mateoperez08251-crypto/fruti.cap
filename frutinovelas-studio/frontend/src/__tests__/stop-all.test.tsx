// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../api'
import { RecoverQueue } from '../components/RecoverQueue'
import { ToastProvider } from '../components/Toast'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function show() {
  render(<QueryClientProvider client={new QueryClient()}><ToastProvider><RecoverQueue /></ToastProvider></QueryClientProvider>)
}

it('does not cancel when the user dismisses confirmation', () => {
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  const stop = vi.spyOn(api, 'stopAllGenerations')
  show()
  fireEvent.click(screen.getByText('Cancelar todas las generaciones'))
  expect(stop).not.toHaveBeenCalled()
})

it('shows incomplete cancellation instead of claiming the queue is empty', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const stop = vi.spyOn(api, 'stopAllGenerations').mockResolvedValue({ cancelled: ['one'], pending: ['two'], stopped_chapters: [] })
  show()
  fireEvent.click(screen.getByText('Cancelar todas las generaciones'))
  await waitFor(() => expect(screen.getByText(/siguen pendientes de confirmación remota/)).toBeTruthy())
  expect(stop).toHaveBeenCalledTimes(1)
})

