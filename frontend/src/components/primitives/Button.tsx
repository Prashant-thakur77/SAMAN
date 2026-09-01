import { forwardRef, type ButtonHTMLAttributes } from 'react'

import { cn } from '../../lib/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
}

// Spec §1.1: buttons are the inverse fill (black-on-white flips to
// white-on-black in dark mode). Nothing else carries a large colour fill.
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-inverse text-bg border border-inverse hover:opacity-90',
  secondary: 'bg-transparent text-ink border border-hairline hover:bg-surface',
  ghost: 'bg-transparent text-muted border border-transparent hover:text-ink hover:bg-surface',
  danger: 'bg-transparent text-danger border border-hairline hover:bg-surface',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', className, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center gap-2 font-medium',
        'transition-opacity duration-150',
        'disabled:cursor-not-allowed disabled:opacity-40',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  )
})
