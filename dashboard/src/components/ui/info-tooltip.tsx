import type { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './tooltip'

export function InfoTooltip({ content, label }: { content: ReactNode; label: string }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label}
            data-dashboard-info-trigger="true"
            className="text-muted-foreground hover:text-foreground focus-visible:outline-ring inline-flex size-[18px] shrink-0 cursor-help items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <svg aria-hidden="true" viewBox="0 0 12 12" className="size-2.5" shapeRendering="crispEdges">
              <path fill="currentColor" d="M5 1h2v2H5zM3 4h4v5h2v2H3V9h2V6H3z" />
            </svg>
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-sm leading-relaxed shadow-none">{content}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
