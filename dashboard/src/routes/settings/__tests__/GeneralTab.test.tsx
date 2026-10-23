import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GeneralTab } from '../GeneralTab'

const i18n = vi.hoisted(() => ({ language: 'zh-CN', resolvedLanguage: undefined as string | undefined, changeLanguage: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n }) }))

beforeEach(() => {
  i18n.language = 'zh-CN'
  i18n.resolvedLanguage = undefined
  i18n.changeLanguage.mockReset()
})
afterEach(cleanup)

describe('常规设置语言选择', () => {
  it('按语言代码归一化地区并优先使用已解析语言', () => {
    const { rerender } = render(<GeneralTab />)
    expect(screen.getByRole('combobox', { name: 'header.switchLanguage' })).toHaveTextContent('中文')
    i18n.resolvedLanguage = 'ja-JP'
    rerender(<GeneralTab />)
    expect(screen.getByRole('combobox', { name: 'header.switchLanguage' })).toHaveTextContent('日本語')
  })

  it.each([['English', 'en'], ['日本語', 'ja'], ['한국어', 'ko'], ['中文', 'zh']])('支持切换到 %s', async (name, code) => {
    const user = userEvent.setup()
    if (code === 'zh') i18n.language = 'en'
    render(<GeneralTab />)
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'header.switchLanguage' }), { key: 'ArrowDown' })
    await user.click(await screen.findByRole('option', { name }))
    expect(i18n.changeLanguage).toHaveBeenCalledWith(code)
  })
})
