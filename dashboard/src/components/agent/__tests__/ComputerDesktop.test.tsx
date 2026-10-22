import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getComputerFrame, getComputerStatus, inputComputer } from '@/lib/computer-api'

import { ComputerDesktop } from '../ComputerDesktop'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/computer-api', () => ({
  controlComputer: vi.fn(), getComputerFrame: vi.fn(), getComputerStatus: vi.fn(),
  inputComputer: vi.fn(), pollComputerOperation: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(getComputerStatus).mockResolvedValue({
    enabled: true, desktop_enabled: true, paused: false, takeover: true,
    sandbox_running: true, agent_state: 'idle', pending_request: null, error: '',
  })
  vi.mocked(getComputerFrame).mockResolvedValue(new Blob(['frame'], { type: 'image/png' }))
  vi.mocked(inputComputer).mockResolvedValue({ success: true, status: 'completed', operation_id: 'click-1' })
})

async function renderDesktop() {
  render(<ComputerDesktop />)
  const control = await screen.findByRole('button', { name: 'chat.computer.screen' })
  const image = screen.getByRole('img', { name: 'chat.computer.screen' })
  Object.defineProperties(image, {
    naturalWidth: { configurable: true, value: 800 },
    naturalHeight: { configurable: true, value: 400 },
  })
  vi.spyOn(image, 'getBoundingClientRect').mockReturnValue(new DOMRect(10, 20, 200, 100))
  return control
}

describe('ComputerDesktop accessible screenshot control', () => {
  it.each(['left', 'right'] as const)('keeps %s pointer clicks in screenshot coordinates', async (button) => {
    const control = await renderDesktop()
    if (button === 'left') fireEvent.click(control, { detail: 1, clientX: 60, clientY: 45 })
    else fireEvent.contextMenu(control, { clientX: 60, clientY: 45 })
    await waitFor(() => expect(inputComputer).toHaveBeenCalledWith(
      [{ action: 'click', button, x: 200, y: 100 }], expect.any(AbortSignal),
    ))
  })

  it.each(['{Enter}', ' '])('activates the screen center with keyboard %s', async (key) => {
    const user = userEvent.setup()
    const control = await renderDesktop()
    control.focus()
    await user.keyboard(key)
    await waitFor(() => expect(inputComputer).toHaveBeenCalledWith(
      [{ action: 'click', button: 'left', x: 400, y: 200 }], expect.any(AbortSignal),
    ))
  })

  it('keeps the screenshot read-only until manual takeover', async () => {
    vi.mocked(getComputerStatus).mockResolvedValue({
      enabled: true, desktop_enabled: true, paused: false, takeover: false,
      sandbox_running: true, agent_state: 'idle', pending_request: null, error: '',
    })
    const control = await renderDesktop()
    expect(control).toBeDisabled()
    fireEvent.click(control, { detail: 1, clientX: 60, clientY: 45 })
    expect(inputComputer).not.toHaveBeenCalled()
  })
})
