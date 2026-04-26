import { useCallback, useMemo } from 'react'
import { Plus, Trash2, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import type { FieldHookComponent } from '@/lib/field-hooks'


// ---------------------------------------------------------------------------
// 数据类型
// ---------------------------------------------------------------------------

type RuleType = 'group' | 'private'

interface TalkValueRule {
  platform: string
  item_id: string
  rule_type: RuleType
  time: string        // "HH:MM-HH:MM"
  value: number       // 0 ~ 1
}

/** 作用范围三态，派生字段而非直接存储。 */
type RuleScope = 'global' | 'group' | 'private'

function deriveScope(rule: TalkValueRule): RuleScope {
  if (!rule.platform && !rule.item_id) return 'global'
  return rule.rule_type === 'private' ? 'private' : 'group'
}

function makeDefaultRule(): TalkValueRule {
  return {
    platform: 'qq',
    item_id: '',
    rule_type: 'group',
    time: '00:00-23:59',
    value: 0.5,
  }
}


// ---------------------------------------------------------------------------
// 时间段选择器（独立组件，便于后续复用）
// ---------------------------------------------------------------------------

const HOURS = Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0'))
const MINUTES = Array.from({ length: 60 }, (_, i) => i.toString().padStart(2, '0'))

function parseTime(value: string): { startH: string; startM: string; endH: string; endM: string } {
  const parts = (value || '00:00-23:59').split('-')
  const [sh = '00', sm = '00'] = (parts[0] || '00:00').split(':')
  const [eh = '23', em = '59'] = (parts[1] || '23:59').split(':')
  return {
    startH: sh.padStart(2, '0'),
    startM: sm.padStart(2, '0'),
    endH: eh.padStart(2, '0'),
    endM: em.padStart(2, '0'),
  }
}

function formatTime(p: { startH: string; startM: string; endH: string; endM: string }): string {
  return `${p.startH}:${p.startM}-${p.endH}:${p.endM}`
}

function TimeRangePicker({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const parsed = useMemo(() => parseTime(value), [value])
  const commit = (patch: Partial<typeof parsed>) => onChange(formatTime({ ...parsed, ...patch }))

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-full justify-start text-xs h-8">
          <Clock className="h-3 w-3 mr-2" />
          {value || '00:00-23:59'}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-3" align="start">
        <div className="space-y-3">
          <Label className="text-xs font-medium">起始</Label>
          <div className="flex gap-2">
            <Select value={parsed.startH} onValueChange={(v) => commit({ startH: v })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-64">{HOURS.map(h => <SelectItem key={h} value={h}>{h} 时</SelectItem>)}</SelectContent>
            </Select>
            <Select value={parsed.startM} onValueChange={(v) => commit({ startM: v })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-64">{MINUTES.map(m => <SelectItem key={m} value={m}>{m} 分</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <Label className="text-xs font-medium">结束</Label>
          <div className="flex gap-2">
            <Select value={parsed.endH} onValueChange={(v) => commit({ endH: v })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-64">{HOURS.map(h => <SelectItem key={h} value={h}>{h} 时</SelectItem>)}</SelectContent>
            </Select>
            <Select value={parsed.endM} onValueChange={(v) => commit({ endM: v })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-64">{MINUTES.map(m => <SelectItem key={m} value={m}>{m} 分</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">
            支持跨夜：结束时间早于起始时间即视为跨天，例如 23:00-02:00
          </p>
        </div>
      </PopoverContent>
    </Popover>
  )
}


// ---------------------------------------------------------------------------
// 单条规则卡片
// ---------------------------------------------------------------------------

function RuleCard({
  index,
  rule,
  onChange,
  onDelete,
}: {
  index: number
  rule: TalkValueRule
  onChange: (patch: Partial<TalkValueRule>) => void
  onDelete: () => void
}) {
  const scope = deriveScope(rule)

  const handleScopeChange = (next: RuleScope) => {
    if (next === 'global') {
      onChange({ platform: '', item_id: '' })
      return
    }
    // 切换到 group/private 时，rule_type 同步；若原本是 global，补默认 platform
    onChange({
      platform: rule.platform || 'qq',
      rule_type: next,
    })
  }

  const isGlobal = scope === 'global'

  return (
    <div className="rounded-lg border p-4 bg-muted/40 space-y-4">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-medium">规则 #{index + 1}</Label>
        <Button variant="ghost" size="sm" onClick={onDelete} className="h-7 text-destructive">
          <Trash2 className="h-3 w-3 mr-1" /> 删除
        </Button>
      </div>

      {/* 作用范围 */}
      <div className="grid grid-cols-3 gap-3">
        <div className="grid gap-1.5">
          <Label className="text-xs">作用范围</Label>
          <Select value={scope} onValueChange={(v) => handleScopeChange(v as RuleScope)}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="global">全局（不限群/私聊）</SelectItem>
              <SelectItem value="group">指定群聊</SelectItem>
              <SelectItem value="private">指定私聊</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid gap-1.5">
          <Label className="text-xs">平台</Label>
          <Input
            value={rule.platform}
            onChange={(e) => onChange({ platform: e.target.value })}
            placeholder="qq"
            disabled={isGlobal}
            className="h-8 text-xs"
          />
        </div>

        <div className="grid gap-1.5">
          <Label className="text-xs">
            {scope === 'group' ? '群号' : scope === 'private' ? '用户 QQ' : 'ID'}
          </Label>
          <Input
            value={rule.item_id}
            onChange={(e) => onChange({ item_id: e.target.value })}
            placeholder={scope === 'group' ? '1098176430' : scope === 'private' ? '252995014' : '（全局规则留空）'}
            disabled={isGlobal}
            className="h-8 text-xs"
          />
        </div>
      </div>

      {/* 时间段 */}
      <div className="grid gap-1.5">
        <Label className="text-xs">时间段</Label>
        <TimeRangePicker
          value={rule.time}
          onChange={(v) => onChange({ time: v })}
        />
      </div>

      {/* 频率值：滑块 + 数字输入 */}
      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label className="text-xs">聊天频率</Label>
          <Input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={rule.value}
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              if (!isNaN(v)) onChange({ value: Math.max(0, Math.min(1, v)) })
            }}
            className="w-20 h-8 text-xs"
          />
        </div>
        <Slider
          value={[rule.value]}
          onValueChange={(vals) => onChange({ value: vals[0] })}
          min={0}
          max={1}
          step={0.01}
          className="w-full"
        />
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>0 (沉默)</span>
          <span>0.5</span>
          <span>1 (正常)</span>
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// 主 Hook 组件
// ---------------------------------------------------------------------------

export const ChatTalkValueRulesVisualHook: FieldHookComponent = ({ value, onChange }) => {
  const rules: TalkValueRule[] = useMemo(() => {
    if (!Array.isArray(value)) return []
    // 兜底兼容：平铺老字段，补全默认值
    return (value as unknown[]).map((raw): TalkValueRule => {
      const r = (raw && typeof raw === 'object') ? raw as Record<string, unknown> : {}
      const ruleType = r.rule_type === 'private' ? 'private' : 'group'
      return {
        platform: typeof r.platform === 'string' ? r.platform : '',
        item_id: r.item_id != null ? String(r.item_id) : '',
        rule_type: ruleType,
        time: typeof r.time === 'string' ? r.time : '00:00-23:59',
        value: typeof r.value === 'number' ? r.value : 0.5,
      }
    })
  }, [value])

  const commit = useCallback((next: TalkValueRule[]) => { onChange?.(next) }, [onChange])

  const addRule = useCallback(() => {
    commit([...rules, makeDefaultRule()])
  }, [rules, commit])

  const updateRule = useCallback((index: number, patch: Partial<TalkValueRule>) => {
    commit(rules.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }, [rules, commit])

  const deleteRule = useCallback((index: number) => {
    commit(rules.filter((_, i) => i !== index))
  }, [rules, commit])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          按规则优先级自上而下匹配：<b>具体会话 &gt; 全局时段规则</b> &gt; 默认 <code>talk_value</code>。
          未命中任何规则时回退到默认值。
        </p>
        <Button variant="outline" size="sm" onClick={addRule} className="h-8">
          <Plus className="h-3 w-3 mr-1" /> 添加规则
        </Button>
      </div>

      {rules.length === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          尚未配置任何规则。所有会话都将使用上方的默认 <code>talk_value</code>。
        </div>
      ) : (
        <div className="space-y-4">
          {rules.map((rule, index) => (
            <RuleCard
              key={index}
              index={index}
              rule={rule}
              onChange={(patch) => updateRule(index, patch)}
              onDelete={() => deleteRule(index)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
