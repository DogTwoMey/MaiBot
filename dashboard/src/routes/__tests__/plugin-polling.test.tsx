import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PluginWebUIPage } from '@/routes/plugin-webui'

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), upload: vi.fn() }))
vi.mock('@tanstack/react-router', () => ({
  useParams: () => ({ pluginId: 'test.plugin', pageId: 'jobs' }),
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/plugin-webui', async (importOriginal) => {
  const registry = { loading: false, error: null, preferences: { hidden: [], order: [] },
    extensions: [{ plugin_id: 'test.plugin', workspace_title: 'Test', pages: [{ id: 'jobs', title: 'Jobs',
      description: '', placement: 'workspace', icon: 'chart', poll_interval_seconds: 5,
      queries: { jobs: { api: 'jobs', version: '1', parameters: {}, confirmation: null } },
      actions: { add: { api: 'add', version: '1', parameters: {}, confirmation: null } },
      content: [{ type: 'text', value: 'Training', children: [], name: null },
        { type: 'upload', label: 'Images', action: 'add', value: null, children: [], name: null }],
    }] }],
  }
  return { ...(await importOriginal<typeof import('@/lib/plugin-webui')>()), usePluginWebUI: () => registry, invokePluginWebUI: mocks.invoke, uploadPluginWebUI: mocks.upload }
})

describe('background job page polling', () => {
  it('keeps per-file upload results after the batch refresh', async () => {
    mocks.invoke.mockResolvedValue({ rows: [] })
    mocks.upload.mockImplementation(async (_plugin, _page, _name, file: File) => {
      if (file.name === 'bad.png') throw new Error('Invalid image')
      return { added: true }
    })
    const view = render(<PluginWebUIPage />)
    await waitFor(() => expect(screen.getByLabelText('Images')).not.toBeDisabled())
    const before = mocks.invoke.mock.calls.length
    fireEvent.change(screen.getByLabelText('Images'), { target: { files: [
      new File(['a'], 'bad.png', { type: 'image/png' }), new File(['b'], 'good.png', { type: 'image/png' }),
    ] } })
    await waitFor(() => expect(mocks.invoke.mock.calls.length).toBeGreaterThan(before))
    await waitFor(() => expect(screen.getByLabelText('Images')).not.toBeDisabled())
    expect(screen.getByText('good.png: 100%')).toBeInTheDocument()
    expect(screen.getByText('bad.png: Error: Invalid image')).toBeInTheDocument()
    view.unmount()
  })
  it('polls queries and stops when leaving the page', async () => {
    vi.useFakeTimers()
    mocks.invoke.mockResolvedValue({ rows: [] })
    try {
      let view: ReturnType<typeof render>
      await act(async () => { view = render(<PluginWebUIPage />) })
      const before = mocks.invoke.mock.calls.length
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(mocks.invoke.mock.calls.length).toBeGreaterThan(before)
      view!.unmount()
      const stopped = mocks.invoke.mock.calls.length
      await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
      expect(mocks.invoke.mock.calls.length).toBe(stopped)
    } finally { vi.useRealTimers() }
  })
})
