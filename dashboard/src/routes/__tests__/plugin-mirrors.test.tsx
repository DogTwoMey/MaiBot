import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { backendApi } from '@/lib/http'
import { invalidatePluginMarketCache } from '@/lib/plugin-api'
import { PluginSettingsDialog } from '../plugins/PluginSettingsDialog'
import { PluginMirrorsPage } from '../plugin-mirrors'

const mocks = vi.hoisted(() => ({ navigate: vi.fn(), toast: vi.fn() }))
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => mocks.navigate }))
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }))
vi.mock('@/lib/http', () => ({ backendApi: { get: vi.fn(), put: vi.fn() } }))
vi.mock('@/lib/plugin-api', () => ({ invalidatePluginMarketCache: vi.fn() }))

const initial = { information_source: 'official', download_source: 'cnb', custom_download_prefix: null }
const endpoint = '/api/webui/plugins/marketplace/source'

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(<QueryClientProvider client={client}><PluginSettingsDialog onClose={onClose} onSaved={onSaved} /></QueryClientProvider>)
  return { client, onClose, onSaved }
}

async function selectSource(label: string, option: string) {
  fireEvent.keyDown(await screen.findByRole('combobox', { name: label }), { key: 'ArrowDown' })
  await userEvent.click(await screen.findByRole('option', { name: option }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(backendApi.get).mockResolvedValue(initial)
  vi.mocked(backendApi.put).mockImplementation(async (_path, options) => options?.body as never)
})
afterEach(cleanup)

describe('插件信息源和下载源设置', () => {
  it('加载当前来源，两个来源独立回显且未修改不能保存', async () => {
    renderSettings()
    expect(await screen.findByRole('combobox', { name: '插件信息源' })).toHaveTextContent('麦麦官方')
    expect(screen.getByRole('combobox', { name: '插件下载源' })).toHaveTextContent('CNB镜像')
    expect(backendApi.get).toHaveBeenCalledWith(endpoint, { errorMessage: '获取插件商店设置失败' })
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled()
  })

  it.each([['CNB镜像', 'cnb'], ['Github源', 'github']])('保存插件信息源 %s，不改变下载源', async (label, value) => {
    const { onSaved, client } = renderSettings()
    await selectSource('插件信息源', label)
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    const saved = { ...initial, information_source: value }
    expect(backendApi.put).toHaveBeenCalledWith(endpoint, { body: saved, errorMessage: '保存插件商店设置失败' })
    expect(client.getQueryData(['plugin-market-source'])).toEqual(saved)
    expect(invalidatePluginMarketCache).toHaveBeenCalledOnce()
    expect(mocks.toast).toHaveBeenCalledWith({ title: '设置已保存' })
  })

  it('下载源切到 Github 后仅在保存时请求，取消不写入', async () => {
    const { onClose } = renderSettings()
    await selectSource('插件下载源', 'Github源')
    expect(backendApi.put).not.toHaveBeenCalled()
    expect(screen.getByRole('combobox', { name: '插件信息源' })).toHaveTextContent('麦麦官方')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(backendApi.put).not.toHaveBeenCalled()
  })

  it('自定义下载源要求非空前缀，和信息源一起原子保存', async () => {
    const { onSaved } = renderSettings()
    await selectSource('插件下载源', '自定义源')
    const input = screen.getByLabelText('Git 克隆前缀')
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'https://mirror.example/https://github.com' } })
    await selectSource('插件信息源', 'Github源')
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    expect(backendApi.put).toHaveBeenCalledWith(endpoint, {
      body: { information_source: 'github', download_source: 'custom', custom_download_prefix: 'https://mirror.example/https://github.com' },
      errorMessage: '保存插件商店设置失败',
    })
  })

  it('自定义前缀回显，切换到内置下载源后仍保留已配置地址', async () => {
    const prefix = 'https://private.example/git'
    vi.mocked(backendApi.get).mockResolvedValue({ ...initial, download_source: 'custom', custom_download_prefix: prefix })
    renderSettings()
    expect(await screen.findByLabelText('Git 克隆前缀')).toHaveValue(prefix)
    await selectSource('插件下载源', 'CNB镜像')
    expect(screen.queryByLabelText('Git 克隆前缀')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(backendApi.put).toHaveBeenCalledWith(endpoint, expect.objectContaining({ body: { ...initial, custom_download_prefix: prefix } })))
  })

  it('改回原始设置时重新禁用保存', async () => {
    renderSettings()
    await selectSource('插件信息源', 'Github源')
    expect(screen.getByRole('button', { name: '保存设置' })).toBeEnabled()
    await selectSource('插件信息源', '麦麦官方')
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled()
  })

  it('加载未完成时不能保存，仍可取消', async () => {
    vi.mocked(backendApi.get).mockReturnValue(new Promise(() => {}))
    const { onClose } = renderSettings()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存设置' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('读取失败展示具体错误，重试后恢复表单', async () => {
    vi.mocked(backendApi.get).mockRejectedValueOnce(new Error('读取来源失败'))
    renderSettings()
    expect(await screen.findByText('读取来源失败')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('combobox', { name: '插件信息源' })).toHaveTextContent('麦麦官方')
    expect(backendApi.get).toHaveBeenCalledTimes(2)
  })

  it('保存失败保留草稿并允许重试，不更新缓存或触发成功回调', async () => {
    vi.mocked(backendApi.put).mockRejectedValueOnce(new Error('保存来源失败'))
    const { client, onSaved } = renderSettings()
    await selectSource('插件信息源', 'Github源')
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '保存设置' })).toBeEnabled())
    expect(screen.getByRole('combobox', { name: '插件信息源' })).toHaveTextContent('Github源')
    expect(client.getQueryData(['plugin-market-source'])).toEqual(initial)
    expect(onSaved).not.toHaveBeenCalled()
    expect(invalidatePluginMarketCache).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  })

  it('保存期间锁定全部设置和关闭操作，完成后解除', async () => {
    let resolve!: (value: unknown) => void
    vi.mocked(backendApi.put).mockReturnValue(new Promise((done) => { resolve = done }))
    const { onClose, onSaved } = renderSettings()
    await selectSource('插件下载源', '自定义源')
    fireEvent.change(screen.getByLabelText('Git 克隆前缀'), { target: { value: 'https://mirror.example' } })
    await userEvent.click(screen.getByRole('button', { name: '保存设置' }))
    expect(screen.getByLabelText('Git 克隆前缀')).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '插件信息源' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '插件下载源' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
    await act(async () => resolve({ ...initial, download_source: 'custom', custom_download_prefix: 'https://mirror.example' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: '取消' })).toBeEnabled()
  })
})

describe('旧插件镜像地址兼容', () => {
  it.each([[false, '/plugins'], [true, '/plugins/embed']])('嵌入模式 %s 替换旧地址，不请求已移除镜像接口', (embedded, to) => {
    render(<PluginMirrorsPage embedded={embedded} />)
    expect(mocks.navigate).toHaveBeenCalledWith({ to, replace: true })
    expect(backendApi.get).not.toHaveBeenCalled()
  })
})
