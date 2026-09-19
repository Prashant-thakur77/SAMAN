import { useLang } from '../lib/i18n'

/** Command-bar language switch: the chrome in Hindi or English; data never changes. */
export function LangToggle() {
  const { lang, setLang } = useLang()
  const next = lang === 'hi' ? 'en' : 'hi'
  return (
    <button
      type="button"
      onClick={() => setLang(next)}
      title={lang === 'hi' ? 'Switch the interface to English' : 'इंटरफ़ेस हिंदी में देखें'}
      aria-label={lang === 'hi' ? 'Switch the interface to English' : 'Switch the interface to Hindi'}
      aria-pressed={lang === 'hi'}
      className="flex h-8 min-w-8 items-center justify-center border border-hairline px-1.5 font-mono text-[11px] text-muted hover:text-ink"
    >
      {lang === 'hi' ? 'EN' : 'हिं'}
    </button>
  )
}
