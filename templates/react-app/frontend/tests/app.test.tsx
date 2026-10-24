import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Application } from '../src/App'

test('the unconfigured app explains its next step without requesting access', () => {
  render(<Application />)
  expect(screen.getByRole('heading', { name: APP_NAME_JSON })).toBeTruthy()
  expect(screen.getByText('Configure this application to get started.')).toBeTruthy()
})
