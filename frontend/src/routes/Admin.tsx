import { useCallback, useEffect, useState } from 'react'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { StatusChip } from '../components/primitives/Chip'
import { Input } from '../components/primitives/Field'
import { TBody, TD, TH, THead, TR, Table } from '../components/primitives/Table'
import { Toggle } from '../components/primitives/Toggle'
import {
  ApiError,
  createUser,
  getHealthPanel,
  getUsers,
  patchUser,
  setSovereign,
  type AdminUser,
  type HealthPanel,
  type Role,
} from '../lib/api'
import { useSession } from '../lib/session'

/**
 * /admin — users, sovereign mode and the health panel (spec §6.13).
 *
 * The health panel reports which engine is *live* in each tier, not which is
 * installed, so it cannot advertise something that would fail on use.
 */
export default function Admin() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [health, setHealth] = useState<HealthPanel | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'danger'; text: string } | null>(null)
  const [draft, setDraft] = useState({ email: '', name: '', role: 'viewer', cpse_code: '' })
  const [busy, setBusy] = useState(false)
  const { user: me } = useSession()

  const load = useCallback(async () => {
    try {
      const [userList, panel] = await Promise.all([getUsers(), getHealthPanel()])
      setUsers(userList.users)
      setRoles(userList.roles)
      setHealth(panel)
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'Could not load administration.',
      })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run(work: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      await load()
      setMessage({ tone: 'ok', text: success })
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : 'That did not work.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        section="Governance"
        title="Administration"
        description="Users and roles, sovereign mode, and which engine is live in each tier."
      />

      {message && (
        <p
          role="status"
          className={`border border-hairline px-4 py-3 text-sm ${
            message.tone === 'ok' ? 'text-ok' : 'text-danger'
          }`}
        >
          {message.text}
        </p>
      )}

      {health && (
        <section className="space-y-4">
          <h2 className="micro-label">Engine health</h2>
          <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-3">
            {(['linkage', 'embedding', 'llm'] as const).map((tier) => {
              const entry = health.capabilities[tier]
              return (
                <div key={tier} className="space-y-2 bg-bg p-5">
                  <p className="micro-label">{tier}</p>
                  <p className="font-mono text-sm">{entry.mode}</p>
                  <p className="text-xs text-muted">{entry.engine}</p>
                  <StatusChip tone={entry.degraded ? 'neutral' : 'ok'}>
                    {entry.degraded ? 'fallback in use' : 'primary engine'}
                  </StatusChip>
                </div>
              )
            })}
          </div>
          {health.capabilities.degraded.length > 0 && (
            <ul className="space-y-1">
              {health.capabilities.degraded.map((note) => (
                <li key={note} className="text-xs text-muted">
                  {note}
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center justify-between gap-4 border border-hairline p-5">
            <div className="max-w-prose space-y-1">
              <p className="micro-label">Sovereign mode</p>
              <p className="text-sm text-muted">
                When on, any configured local model is ignored and the copilot answers from its
                reviewed queries alone. Nothing leaves the machine either way — this makes that
                guarantee explicit and visible.
              </p>
            </div>
            <Toggle
              checked={health.sovereign_mode}
              disabled={busy}
              label="Sovereign mode"
              onChange={(next) =>
                void run(() => setSovereign(next), `Sovereign mode ${next ? 'on' : 'off'}.`)
              }
            />
          </div>

          <div className="grid gap-px border border-hairline bg-hairline sm:grid-cols-3 lg:grid-cols-4">
            {Object.entries(health.counts).map(([key, value]) => (
              <div key={key} className="space-y-1 bg-bg p-4">
                <p className="micro-label">{key.replace(/_/g, ' ')}</p>
                <p className="font-mono text-sm">{value.toLocaleString('en-IN')}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-4 border border-hairline p-4">
            <StatusChip tone={health.smart_create.prevented > 0 ? 'ok' : 'neutral'}>
              {health.smart_create.prevented} duplicates prevented at source
            </StatusChip>
            <span className="max-w-prose font-mono text-xs text-muted">
              {health.smart_create.checks} checks ·{' '}
              {health.smart_create.created_anyway} overridden ·{' '}
              {health.smart_create.prevention_rate === null
                ? 'no decided checks yet'
                : `${Math.round(health.smart_create.prevention_rate * 100)}% prevention rate`}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-4 border border-hairline p-4">
            <StatusChip tone={health.audit.valid ? 'ok' : 'danger'}>
              {health.audit.valid ? 'audit chain intact' : 'audit chain broken'}
            </StatusChip>
            <span className="font-mono text-xs text-muted">
              {health.audit.events} events · {health.database}
            </span>
          </div>
        </section>
      )}

      {health && (
        <section className="space-y-4">
          <h2 className="micro-label">Who can see what</h2>
          <p className="max-w-prose text-sm text-muted">
            {health.visibility_policy.summary}
          </p>
          <Table>
            <THead>
              <TH>Role</TH>
              <TH>Sees</TH>
              <TH>Withheld</TH>
            </THead>
            <TBody>
              {health.visibility_policy.rules.map((rule) => (
                <TR key={rule.who}>
                  <TD mono>{rule.who}</TD>
                  <TD>{rule.sees}</TD>
                  <TD className="text-muted">{rule.withheld}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <p className="max-w-prose text-xs text-muted">
            {health.visibility_policy.enforced_in}
          </p>
        </section>
      )}

      <section className="space-y-4">
        <h2 className="micro-label">Users</h2>
        <Table>
          <THead>
            <TH>Name</TH>
            <TH>Email</TH>
            <TH>CPSE</TH>
            <TH>Role</TH>
            <TH>Status</TH>
          </THead>
          <TBody>
            {users.map((user) => (
              <TR key={user.id}>
                <TD>{user.name}</TD>
                <TD mono>{user.email}</TD>
                <TD mono>{user.cpse_code ?? '—'}</TD>
                <TD>
                  <select
                    value={user.role}
                    disabled={busy}
                    onChange={(e) =>
                      void run(
                        () => patchUser(user.id, { role: e.target.value }),
                        `${user.name} is now ${e.target.value}.`,
                      )
                    }
                    className="h-8 border border-hairline bg-bg px-2 text-xs"
                  >
                    {roles.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </TD>
                <TD>
                  <Button
                    size="sm"
                    variant={user.active ? 'secondary' : 'primary'}
                    disabled={busy || user.id === me?.id}
                    title={
                      user.id === me?.id
                        ? 'You cannot disable the account you are signed in with.'
                        : undefined
                    }
                    onClick={() =>
                      void run(
                        () => patchUser(user.id, { active: !user.active }),
                        `${user.name} ${user.active ? 'disabled' : 'enabled'}.`,
                      )
                    }
                  >
                    {user.active ? 'Disable' : 'Enable'}
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>

        <div className="space-y-3 border border-hairline p-5">
          <p className="micro-label">Add a user</p>
          <div className="flex flex-wrap gap-3">
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Full name"
              className="max-w-[14rem]"
              aria-label="Name"
            />
            <Input
              value={draft.email}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
              placeholder="name@cpse.in"
              className="max-w-[16rem] font-mono"
              aria-label="Email"
            />
            <select
              value={draft.role}
              onChange={(e) => setDraft({ ...draft, role: e.target.value })}
              className="h-10 border border-hairline bg-bg px-3 text-sm"
              aria-label="Role"
            >
              {roles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
            <Input
              value={draft.cpse_code}
              onChange={(e) => setDraft({ ...draft, cpse_code: e.target.value.toUpperCase() })}
              placeholder="CPSE (optional)"
              className="max-w-[10rem] font-mono"
              aria-label="CPSE code"
            />
            <Button
              variant="primary"
              disabled={busy || !draft.email.trim() || !draft.name.trim()}
              onClick={() =>
                void run(
                  () =>
                    createUser({
                      email: draft.email.trim(),
                      name: draft.name.trim(),
                      role: draft.role,
                      cpse_code: draft.cpse_code.trim() || null,
                    }),
                  `${draft.name} added.`,
                ).then(() => setDraft({ email: '', name: '', role: 'viewer', cpse_code: '' }))
              }
            >
              Add
            </Button>
          </div>
          <p className="text-xs text-muted">New accounts start with the password “demo”.</p>
        </div>
      </section>
    </div>
  )
}
