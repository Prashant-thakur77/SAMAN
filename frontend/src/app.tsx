import { AnimatePresence } from 'framer-motion'
import { Route, Routes, useLocation } from 'react-router-dom'

import { RequireRole } from './components/RequireRole'
import { RouteTransition } from './components/RouteTransition'
import { Shell } from './components/Shell'
import Admin from './routes/Admin'
import Audit from './routes/Audit'
import Cluster from './routes/Cluster'
import Copilot from './routes/Copilot'
import DashExecutive from './routes/DashExecutive'
import DashOpportunity from './routes/DashOpportunity'
import Home from './routes/Home'
import Item from './routes/Item'
import Login from './routes/Login'
import Migration from './routes/Migration'
import NotFound from './routes/NotFound'
import Onboard from './routes/Onboard'
import Search from './routes/Search'
import Workbench from './routes/Workbench'

/** Every route inside the shell, wrapped in the §1.5 route transition. */
const SHELL_ROUTES = [
  { path: '/', element: <Home /> },
  { path: '/search', element: <Search /> },
  { path: '/items/:id', element: <Item /> },
  { path: '/workbench', element: <Workbench /> },
  { path: '/clusters/:id', element: <Cluster /> },
  { path: '/dashboard/executive', element: <DashExecutive /> },
  { path: '/dashboard/opportunity', element: <DashOpportunity /> },
  { path: '/copilot', element: <Copilot /> },
  { path: '/audit', element: <Audit /> },
  { path: '/onboard', element: <Onboard /> },
  {
    path: '/migration',
    element: (
      <RequireRole roles={['registrar', 'admin']}>
        <Migration />
      </RequireRole>
    ),
  },
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

  // /login stands outside the shell: no sidebar, no command bar.
  if (location.pathname === '/login') {
    return (
      <AnimatePresence mode="wait">
        <RouteTransition key="login">
          <Login />
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
            <Route key={path} path={path} element={<RouteTransition>{element}</RouteTransition>} />
          ))}
        </Routes>
      </AnimatePresence>
    </Shell>
  )
}
