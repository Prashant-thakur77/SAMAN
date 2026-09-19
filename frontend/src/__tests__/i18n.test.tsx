/**
 * The interface in Hindi: chrome translates, data and unknown strings do not,
 * and the choice is remembered on the device.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { LangToggle } from '../components/LangToggle'
import { PageHeader } from '../components/PageHeader'
import { LangProvider, useT } from '../lib/i18n'

function Probe({ s }: { s: string }) {
  const t = useT()
  return <span data-testid="probe">{t(s)}</span>
}

describe('the Hindi interface', () => {
  beforeEach(() => localStorage.clear())

  it('starts in English and switches the chrome, keeping data as it is', () => {
    render(
      <LangProvider>
        <LangToggle />
        <PageHeader section="Review" title="Workbench" description="Two rows, side by side." />
        <Probe s="BEARING BALL 6205 ZZ SKF" />
      </LangProvider>,
    )
    expect(screen.getByRole('heading', { name: 'Workbench' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /switch the interface to hindi/i }))
    expect(screen.getByRole('heading', { name: 'वर्कबेंच' })).toBeInTheDocument()
    expect(screen.getByText('समीक्षा')).toBeInTheDocument()
    expect(screen.getByText('दो पंक्तियाँ, आमने-सामने।')).toBeInTheDocument()
    // A description is data: it is never translated.
    expect(screen.getByTestId('probe')).toHaveTextContent('BEARING BALL 6205 ZZ SKF')
    expect(localStorage.getItem('saman.lang')).toBe('hi')
    expect(document.documentElement.lang).toBe('hi')
  })

  it('a string nobody translated stays readable in English', () => {
    localStorage.setItem('saman.lang', 'hi')
    render(
      <LangProvider>
        <Probe s="A sentence with no Hindi yet" />
      </LangProvider>,
    )
    expect(screen.getByTestId('probe')).toHaveTextContent('A sentence with no Hindi yet')
  })
})
