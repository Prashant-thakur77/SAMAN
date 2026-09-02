import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { NAV } from '../lib/nav'

/**
 * Announce route changes to assistive technology.
 *
 * A single-page app swaps the whole content column without moving focus or
 * changing the document, so a screen reader says nothing at all — the user
 * activates a link and, as far as they can tell, nothing happens. This speaks
 * the new page's name into a polite live region and moves focus to the main
 * landmark so the next Tab starts from the content rather than back at the top
 * of the sidebar.
 */
export function RouteAnnouncer() {
  const { pathname } = useLocation()
  const [message, setMessage] = useState('')
  const first = useRef(true)

  useEffect(() => {
    // Not on the first render: the page was not navigated to, it was loaded,
    // and the browser already announced it.
    if (first.current) {
      first.current = false
      return
    }
    const match =
      NAV.find((item) => item.path !== '/' && pathname.startsWith(item.path)) ??
      NAV.find((item) => item.path === pathname)
    setMessage(`${match?.label ?? document.title}, page loaded`)

    const main = document.getElementById('main-content')
    main?.focus({ preventScroll: true })
  }, [pathname])

  return (
    <p aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </p>
  )
}
