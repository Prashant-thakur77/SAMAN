import { AnimatePresence } from 'framer-motion'
import { Suspense, lazy } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'

import { useSession } from './lib/session'
import { RequireRole } from './components/RequireRole'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RouteTransition } from './components/RouteTransition'
import { Shell } from './components/Shell'
import Admin from './routes/Admin'
import Audit from './routes/Audit'
import Cluster from './routes/Cluster'
import Copilot from './routes/Copilot'
// Recharts is ~200 kB and only two screens need it, so the dashboards are
// split out of the initial bundle (spec §9: keep the bundle lean).
const DashExecutive = lazy(() => import('./routes/DashExecutive'))
const DashOpportunity = lazy(() => import('./routes/DashOpportunity'))

import Home from './routes/Home'
import Item from './routes/Item'
import Landing from './routes/Landing'
import Login from './routes/Login'
import Migration from './routes/Migration'
import NotFound from './routes/NotFound'
import Onboard from './routes/Onboard'
import Search from './routes/Search'
import Pprl from './routes/Pprl'
import SmartCreate from './routes/SmartCreate'
import Substitutes from './routes/Substitutes'
import Workbench from './routes/Workbench'

/** Every route inside the shell, wrapped in the §1.5 route transition. */
const SHELL_ROUTES = [
  { path: '/', element: <Home /> },
  { path: '/search', element: <Search /> },
  { path: '/items/:id', element: <Item /> },
  { path: '/workbench', element: <Workbench /> },
  { path: '/substitutes', element: <Substitutes /> },
  { path: '/clusters/:id', element: <Cluster /> },
  { path: '/dashboard/executive', element: <DashExecutive /> },
  { path: '/dashboard/opportunity', element: <DashOpportunity /> },
  { path: '/copilot', element: <Copilot /> },
  { path: '/audit', element: <Audit /> },
  { path: '/onboard', element: <Onboard /> },
  // Read-only for a steward: the apply and rollback controls are role-gated
  // inside the screen, and other CPSEs' valuations are withheld server-side.
  { path: '/migration', element: <Migration /> },
  { path: '/smart-create', element: <SmartCreate /> },
  { path: '/pprl', element: <Pprl /> },
  {
    path: '/admin',
    element: (
      <RequireRole roles={['registrar', 'admin']}>
        <Admin />
      </RequireRole>
    ),
  },
  { path: '*', element: <NotFound /> },
]

export default function App() {
  const location = useLocation()
  const { user, loading } = useSession()

  // `/` is two different screens depending on who is asking: the public front
  // page for a visitor, the operator's home for anyone signed in. `/welcome`
  // reaches the front page either way, which is what the footer, the demo
  // script and a signed-in user showing somebody else the system all need.
  const atRoot = location.pathname === '/'
  const showLanding = location.pathname === '/welcome' || (atRoot && !user)

  // The session is one request away on a cold load, and `user` is null until it
  // lands. Rendering the landing page in that gap would flash the front page at
  // a signed-in user every time they open the application.
  if (atRoot && loading) return <div className="min-h-screen bg-bg" />

  // /login and the landing page stand outside the shell: no sidebar, no
  // command bar.
  //
  // `initial={false}` for the same reason the shell routes use it: a route
  // transition needs two routes, and there is no outgoing one on a cold load.
  // Without it the first screen anybody sees fades up from nothing, which on a
  // cold bundle takes long enough to look like a slow application rather than a
  // deliberate animation.
  if (location.pathname === '/login' || showLanding) {
    return (
      <AnimatePresence mode="wait" initial={false}>
        <RouteTransition key={showLanding ? 'landing' : 'login'}>
          <ErrorBoundary>{showLanding ? <Landing /> : <Login />}</ErrorBoundary>
        </RouteTransition>
      </AnimatePresence>
    )
  }

  return (
    <Shell>
      {/* `mode="wait"` so the outgoing 120ms fade finishes before the incoming
          240ms slide begins — otherwise the two routes overlap mid-transition. */}
      <AnimatePresence mode="wait" initial={false}>
        <Routes location={location} key={location.pathname}>
          {SHELL_ROUTES.map(({ path, element }) => (
            <Route
              key={path}
              path={path}
              element={
                <RouteTransition>
                  {/* Keyed on the path so navigating away from a broken screen
                      resets the boundary rather than sticking on the error. */}
                  <ErrorBoundary key={path}>
                    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
                      {element}
                    </Suspense>
                  </ErrorBoundary>
                </RouteTransition>
              }
            />
          ))}
        </Routes>
      </AnimatePresence>
    </Shell>
  )
}
