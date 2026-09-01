import { cn } from '../../lib/cn'

/** Switch built from hairlines only — no fills beyond the inverse knob. */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-6 w-11 shrink-0 border transition-colors duration-150',
        checked ? 'border-inverse bg-inverse' : 'border-hairline bg-transparent',
        'disabled:cursor-not-allowed disabled:opacity-40',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'absolute top-1/2 h-4 w-4 -translate-y-1/2 transition-all duration-150 ease-saman',
          checked ? 'left-[calc(100%-1.25rem)] bg-bg' : 'left-1 bg-muted',
        )}
      />
    </button>
  )
}
