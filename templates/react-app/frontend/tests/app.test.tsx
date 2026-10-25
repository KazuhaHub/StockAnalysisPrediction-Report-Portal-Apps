import { act, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Application } from '../src/App'

test('the unconfigured app explains its next step without requesting access', () => {
  render(<Application />)
  expect(screen.queryByRole('heading', { name: APP_NAME_JSON })).toBeNull()
  act(() => window.dispatchEvent(new MessageEvent('message', {
    source: window.parent,
    data: { type: 'rp:init', locale: 'en-US', theme: { dark: true, colorBgLayout: '#000000' } },
  })))
  expect(screen.getByRole('heading', { name: APP_NAME_JSON })).toBeTruthy()
  expect(screen.getByText('Configure this application to get started.')).toBeTruthy()
})
