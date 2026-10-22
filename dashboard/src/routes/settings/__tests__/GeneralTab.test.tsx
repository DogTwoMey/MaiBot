import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
    expect(screen.getByRole('combobox', { name: 'header.switchLanguage' })).toHaveValue('zh')
    expect(screen.getByRole('option', { name: '中文' })).toHaveProperty('selected', true)
    i18n.resolvedLanguage = 'ja-JP'
    rerender(<GeneralTab />)
    expect(screen.getByRole('combobox', { name: 'header.switchLanguage' })).toHaveValue('ja')
  })

  it.each([['English', 'en'], ['日本語', 'ja'], ['한국어', 'ko'], ['中文', 'zh']])('支持切换到 %s', (name, code) => {
    render(<GeneralTab />)
    expect(screen.getByRole('option', { name })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'header.switchLanguage' }), { target: { value: code } })
    expect(i18n.changeLanguage).toHaveBeenCalledWith(code)
  })
})
