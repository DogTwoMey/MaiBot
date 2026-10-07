import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AboutTab } from '../AboutTab'
import { SettingsPage } from '../index'

const { navigateMock, routerState } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
  routerState: { searchStr: '', hash: '' },
}))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigateMock,
  useRouterState: ({
    select,
  }: {
    select: (state: { location: { searchStr: string; hash: string } }) => string
  }) => select({ location: routerState }),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../AppearanceTab', () => ({ AppearanceTab: () => <div>外观页内容</div> }))
vi.mock('../SecurityTab', () => ({ SecurityTab: () => <div>安全页内容</div> }))
vi.mock('../OtherTab', () => ({ OtherTab: () => <div>其他页内容</div> }))

beforeEach(() => {
  navigateMock.mockClear()
  routerState.searchStr = ''
  routerState.hash = ''
})
afterEach(cleanup)

describe('WebUI 设置与关于页', () => {
  it('切换标签时保留独立设置页的查询参数', async () => {
    routerState.searchStr = '?mode=webui&tab=security&extra=keep'
    const view = render(<SettingsPage />)
    expect(screen.getByText('安全页内容')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('tab', { name: 'settings.tabs.other' }))
    expect(navigateMock).toHaveBeenCalledWith({
      href: '/settings?tab=other&extra=keep',
      replace: true,
    })
    routerState.searchStr = '?mode=webui&tab=other&extra=keep'
    view.rerender(<SettingsPage />)
    expect(screen.getByText('其他页内容')).toBeInTheDocument()
  })

  it('缺省或未知标签显示外观页', () => {
    const view = render(<SettingsPage />)
    expect(screen.getByText('外观页内容')).toBeInTheDocument()
    routerState.searchStr = '?tab=unknown'
    view.rerender(<SettingsPage />)
    expect(screen.getByText('外观页内容')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'settings.title' })).not.toBeInTheDocument()
  })

  it('切回外观页使用独立设置页路径', async () => {
    routerState.searchStr = '?tab=about&mode=webui'
    render(<SettingsPage />)
    await userEvent.setup().click(screen.getByRole('tab', { name: 'settings.tabs.appearance' }))
    expect(navigateMock).toHaveBeenCalledWith({ href: '/settings', replace: true })
  })

  it('关于页展示版本、技术栈、许可证和安全的外部链接属性', () => {
    render(<AboutTab />)
    expect(screen.getByText(/MaiBot Dashboard/)).toBeInTheDocument()
    expect(screen.getByText('React 19.2.0')).toBeInTheDocument()
    expect(screen.getByText('GPLv3')).toBeInTheDocument()
    expect(screen.getByText('TypeScript')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /settings.about.visitGitHub/ })).toHaveAttribute(
      'href',
      'https://github.com/Mai-with-u/MaiBot-Dashboard'
    )
    expect(screen.getByRole('link', { name: '@MotricSeven' })).toHaveAttribute(
      'rel',
      'noopener noreferrer'
    )
  })
})
