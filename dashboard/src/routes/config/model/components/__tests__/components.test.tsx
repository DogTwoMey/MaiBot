import type { ReactNode } from 'react'
import type { ModelTestResult } from '@/lib/config-api'
import type { ModelInfo } from '../../types'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DataPagination } from '@/components/ui/data-pagination'

import { ModelCardList } from '../ModelCardList'
import { ModelTable } from '../ModelTable'
import { TaskAssignmentBoard } from '../TaskAssignmentBoard'

vi.mock('@/components/ui/checkbox', () => ({
  Checkbox: ({ checked, onCheckedChange }: { checked?: boolean; onCheckedChange?: () => void }) => (
    <input type="checkbox" checked={Boolean(checked)} onChange={() => onCheckedChange?.()} />
  ),
}))

vi.mock('@/components/ui/multi-select', () => ({
  MultiSelect: ({
    options,
    selected,
    onChange,
  }: {
    options: Array<{ label: string; value: string }>
    selected: string[]
    onChange: (value: string[]) => void
  }) => (
    <div data-testid="multi-select" data-selected={selected.join(',')}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange([...selected, option.value])}
        >
          {option.label}
        </button>
      ))}
    </div>
  ),
}))

vi.mock('@/components/ui/slider', () => ({
  Slider: ({
    value,
    onValueChange,
  }: {
    value: number[]
    onValueChange: (value: number[]) => void
  }) => (
    <button type="button" data-testid="temperature-slider" onClick={() => onValueChange([1.25])}>
      {value[0]}
    </button>
  ),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    value,
    onValueChange,
  }: {
    children: ReactNode
    value: string
    onValueChange: (value: string) => void
  }) => (
    <div data-testid="select-root" data-value={value}>
      {children}
      <button type="button" onClick={() => onValueChange(value === '10' ? '20' : 'random')}>
        切换选项
      </button>
    </div>
  ),
  SelectTrigger: ({ children, ...props }: { children: ReactNode }) => (
    <div {...props}>{children}</div>
  ),
  SelectValue: () => <span>当前选项</span>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

function makeModel(name: string, overrides: Partial<ModelInfo> = {}): ModelInfo {
  return {
    name,
    model_identifier: `${name}-id`,
    model_type: 'llm',
    api_provider: 'provider-a',
    price_in: 1,
    price_out: 2,
    temperature: 0.7,
    visual: false,
    ...overrides,
  }
}

function makeResult(overrides: Partial<ModelTestResult> = {}): ModelTestResult {
  return {
    success: true,
    model_name: 'alpha',
    visual_tested: true,
    tool_call_ok: true,
    response: 'ok',
    reasoning: '',
    tool_calls: [],
    latency_ms: 1250,
    error: null,
    prompt_tokens: 1,
    completion_tokens: 2,
    total_tokens: 3,
    ...overrides,
  }
}

afterEach(() => cleanup())

describe('ModelTable', () => {
  it('渲染模型属性和测试状态，并使用 allModels 中的真实索引', async () => {
    const user = userEvent.setup()
    const hidden = makeModel('hidden')
    const alpha = makeModel('alpha', { visual: true })
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    const onTest = vi.fn()
    const onToggleSelection = vi.fn()
    render(
      <ModelTable
        paginatedModels={[alpha]}
        allModels={[hidden, alpha]}
        filteredModels={[alpha]}
        selectedModels={new Set([1])}
        onEdit={onEdit}
        onDelete={onDelete}
        onTest={onTest}
        onAdd={vi.fn()}
        onToggleSelection={onToggleSelection}
        onToggleSelectAll={vi.fn()}
        isModelUsed={() => true}
        testingModels={new Set()}
        modelTestResults={new Map([['alpha', makeResult()]])}
        searchQuery=""
      />
    )

    expect(screen.getByText('alpha-id')).toBeInTheDocument()
    expect(screen.getByLabelText('已使用')).toBeInTheDocument()
    expect(screen.getByLabelText('已启用视觉')).toBeInTheDocument()
    const successName = screen.getByLabelText('测试通过：文本、视觉与工具调用正常，耗时 1.25s')
    expect(successName).toHaveTextContent('alpha')
    expect(successName).toHaveClass('border-green-500')
    expect(screen.queryByRole('columnheader', { name: '测试' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '测试模型 alpha' }))
    await user.click(screen.getByRole('button', { name: '编辑模型 alpha' }))
    await user.click(screen.getByRole('button', { name: '删除模型 alpha' }))
    await user.click(screen.getAllByRole('checkbox')[1])

    expect(onTest).toHaveBeenCalledWith('alpha')
    expect(onEdit).toHaveBeenCalledWith(alpha, 1)
    expect(onDelete).toHaveBeenCalledWith(1)
    expect(onToggleSelection).toHaveBeenCalledWith(1)
  })

  it('展示空态并区分无配置与搜索无结果', () => {
    const props = {
      paginatedModels: [],
      allModels: [],
      filteredModels: [],
      selectedModels: new Set<number>(),
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onTest: vi.fn(),
      onAdd: vi.fn(),
      onToggleSelection: vi.fn(),
      onToggleSelectAll: vi.fn(),
      isModelUsed: vi.fn(() => false),
      testingModels: new Set<string>(),
      modelTestResults: new Map<string, ModelTestResult>(),
    }
    const { rerender } = render(<ModelTable {...props} searchQuery="" />)
    expect(screen.getByText('暂无模型配置')).toBeInTheDocument()
    rerender(<ModelTable {...props} searchQuery="missing" />)
    expect(screen.getByText('未找到匹配的模型')).toBeInTheDocument()
  })

  it('正在测试时禁用测试按钮，失败结果暴露错误原因', () => {
    const alpha = makeModel('alpha')
    const props = {
      paginatedModels: [alpha],
      allModels: [alpha],
      filteredModels: [alpha],
      selectedModels: new Set<number>(),
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onTest: vi.fn(),
      onAdd: vi.fn(),
      onToggleSelection: vi.fn(),
      onToggleSelectAll: vi.fn(),
      isModelUsed: vi.fn(() => false),
      searchQuery: '',
    }
    const { rerender } = render(
      <ModelTable {...props} testingModels={new Set(['alpha'])} modelTestResults={new Map()} />
    )
    expect(screen.getByLabelText('正在测试模型能力')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '测试模型 alpha' })).toBeDisabled()

    rerender(
      <ModelTable
        {...props}
        testingModels={new Set()}
        modelTestResults={new Map([['alpha', makeResult({ success: false, error: '鉴权失败' })]])}
      />
    )
    expect(screen.getByLabelText('鉴权失败')).toHaveClass('border-red-500')
  })
})

describe('ModelCardList', () => {
  it('移动卡片展示模型并触发测试、编辑、删除', async () => {
    const user = userEvent.setup()
    const first = makeModel('first')
    const alpha = makeModel('alpha')
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    const onTest = vi.fn()
    render(
      <ModelCardList
        paginatedModels={[alpha]}
        allModels={[first, alpha]}
        onEdit={onEdit}
        onDelete={onDelete}
        onTest={onTest}
        isModelUsed={() => false}
        testingModels={new Set()}
        modelTestResults={new Map()}
        searchQuery=""
      />
    )

    expect(screen.getByText('provider-a')).toBeInTheDocument()
    expect(screen.getByLabelText('未使用')).toBeInTheDocument()
    expect(screen.getByLabelText('未测试：尚未执行模型能力测试')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '测试模型 alpha' }))
    await user.click(screen.getByRole('button', { name: '编辑模型 alpha' }))
    await user.click(screen.getByRole('button', { name: '删除模型 alpha' }))
    expect(onTest).toHaveBeenCalledWith('alpha')
    expect(onEdit).toHaveBeenCalledWith(alpha, 1)
    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('空列表根据搜索词显示对应文案', () => {
    const props = {
      paginatedModels: [],
      allModels: [],
      onEdit: vi.fn(),
      onDelete: vi.fn(),
      onTest: vi.fn(),
      isModelUsed: vi.fn(() => false),
      testingModels: new Set<string>(),
      modelTestResults: new Map<string, ModelTestResult>(),
    }
    const { rerender } = render(<ModelCardList {...props} searchQuery="" />)
    expect(screen.getByText('暂无模型配置')).toBeInTheDocument()
    rerender(<ModelCardList {...props} searchQuery="x" />)
    expect(screen.getByText('未找到匹配的模型')).toBeInTheDocument()
  })
})

describe('TaskAssignmentBoard', () => {
  it('回复路由提示词支持编辑与清空', () => {
    const onChange = vi.fn()
    render(<TaskAssignmentBoard
      fields={[{ name: 'replyer', type: 'object', label: '回复', description: '', required: false }]}
      taskConfig={{ replyer: { model_list: [], routing_prompt: '日常交流使用 Aliyun。' } }}
      models={[]} webServices={[]} openTask="replyer" onOpenTaskChange={vi.fn()}
      onChange={onChange} onAddWebService={vi.fn()} hasProviders fallbackLabel={(field) => field.name}
    />)
    const prompt = screen.getByLabelText('模型路由提示词')
    expect(prompt).toHaveValue('日常交流使用 Aliyun。')
    fireEvent.change(prompt, { target: { value: '技术问题使用 DeepSeek。' } })
    expect(onChange).toHaveBeenCalledWith('replyer', 'routing_prompt', '技术问题使用 DeepSeek。')
    fireEvent.change(prompt, { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith('replyer', 'routing_prompt', '')
  })
})

describe('DataPagination', () => {
  it('空数据展示零页且禁用翻页操作', () => {
    render(<DataPagination total={0} page={1} pageSize={10} onPageChange={vi.fn()} />)
    expect(screen.getByText('0 条 · 第 0/0 页')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '第 1 页' })).toBeDisabled()
  })

  it('展示当前页并支持首尾、前后页和回车跳转', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<DataPagination total={125} page={2} pageSize={10} onPageChange={onPageChange} />)
    expect(screen.getByText('125 条 · 第 2/13 页')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '第 2 页' })).toHaveAttribute('aria-current', 'page')
    await user.click(screen.getByRole('button', { name: '第 1 页' }))
    await user.click(screen.getByRole('button', { name: '上一页' }))
    await user.click(screen.getByRole('button', { name: '下一页' }))
    await user.click(screen.getByRole('button', { name: '第 13 页' }))
    await user.click(screen.getByRole('button', { name: '跳转到指定页' }))
    const input = screen.getByRole('spinbutton')
    await user.clear(input)
    await user.type(input, '2{Enter}')
    expect(onPageChange.mock.calls.map(([page]) => page)).toEqual([1, 1, 3, 13, 2])
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('每页条数变更回调提供数字，首尾页禁用越界翻页', async () => {
    const user = userEvent.setup()
    const onPageSizeChange = vi.fn()
    const props = { total: 25, pageSize: 10, onPageChange: vi.fn(), onPageSizeChange }
    const { rerender } = render(<DataPagination {...props} page={1} />)
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '切换选项' }))
    expect(onPageSizeChange).toHaveBeenCalledWith(20)
    rerender(<DataPagination {...props} page={3} />)
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  })
})
