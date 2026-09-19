import { StatusChip } from './primitives/Chip'
import { TBody, TD, TH, THead, TR, Table } from './primitives/Table'
import type { LearnStatus } from '../lib/api'

/**
 * The learned model's retraining loop, beneath the model itself on /admin.
 *
 * Three things a registrar wants to see and nothing they can click: whether
 * the champion/challenger loop is on and how close it is to running, what
 * every attempt did and why, how the model does per class, and the threshold
 * cuts the labels would suggest — suggested, not applied. Thresholds change
 * in match.py, by a person, with a reason.
 */
export function RetrainingPanel({ status }: { status: LearnStatus }) {
  const loop = status.auto_retrain
  const history = status.history ?? []
  const perClass = status.model?.holdout?.per_class ?? []
  const suggestions = status.suggestions
  const pct = (value: number | null | undefined) =>
    value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
  const num = (value: number | null | undefined, digits = 3) =>
    value === null || value === undefined ? '—' : value.toFixed(digits)
  return (
    <div className="space-y-5 card p-5" data-testid="retraining">
      <div className="max-w-prose space-y-1">
        <p className="micro-label">Retraining · champion and challenger</p>
        <p className="text-xs text-muted">
          After every {loop?.every ?? '—'} reviewer decisions a challenger is trained on all labels
          and measured on the held-out split. It replaces the champion only if it is not worse;
          every attempt is recorded below either way. Simulated labels never count toward the
          trigger.
        </p>
      </div>

      <div className="grid gap-px overflow-hidden rounded-xl border border-hairline bg-hairline sm:grid-cols-4">
        <div className="space-y-1 bg-surface p-4">
          <p className="micro-label">auto-retrain</p>
          <p className="font-mono text-sm tabular-nums">{loop?.enabled ? 'on' : 'off'}</p>
        </div>
        <div className="space-y-1 bg-surface p-4">
          <p className="micro-label">every</p>
          <p className="font-mono text-sm tabular-nums">{loop?.every ?? '—'} reviewer labels</p>
        </div>
        <div className="space-y-1 bg-surface p-4">
          <p className="micro-label">labels since</p>
          <p className="font-mono text-sm tabular-nums">{loop?.labels_since ?? '—'}</p>
        </div>
        <div className="space-y-1 bg-surface p-4">
          <p className="micro-label">due</p>
          <p className="font-mono text-sm tabular-nums">
            {loop?.running ? 'running now' : loop?.due ? 'yes' : 'not yet'}
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="micro-label">attempts · newest first</p>
        {history.length === 0 ? (
          <p className="text-xs text-muted">No training attempt recorded yet.</p>
        ) : (
          <Table>
            <THead>
              <TH>Time</TH>
              <TH align="right">Labels</TH>
              <TH align="right">Held-out AUC</TH>
              <TH align="right">Grey AUC</TH>
              <TH>Outcome</TH>
              <TH>Reason</TH>
            </THead>
            <TBody>
              {history.map((attempt) => (
                <TR key={`${attempt.ts}-${attempt.last_label_id}`}>
                  <TD mono className="tabular-nums">
                    {new Date(attempt.ts).toLocaleString('en-IN')}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {attempt.n_labels ?? '—'}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {num(attempt.holdout_auc, 4)}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {num(attempt.grey_auc, 4)}
                  </TD>
                  <TD>
                    <StatusChip tone={attempt.promoted ? 'ok' : 'neutral'}>
                      {attempt.promoted ? 'promoted' : 'kept'}
                    </StatusChip>
                  </TD>
                  <TD className="text-xs text-muted" title={attempt.reason}>
                    <span className="block max-w-md truncate">{attempt.reason}</span>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>

      {perClass.length > 0 && (
        <div className="space-y-2">
          <p className="micro-label">held-out, per class · model beside the pipeline's score</p>
          <Table>
            <THead>
              <TH>Class</TH>
              <TH align="right">Pairs</TH>
              <TH align="right">Model AUC</TH>
              <TH align="right">Pipeline AUC</TH>
              <TH align="right">Precision</TH>
              <TH align="right">Recall</TH>
            </THead>
            <TBody>
              {perClass.map((row) => (
                <TR key={row.class_code}>
                  <TD mono>{row.class_code}</TD>
                  <TD mono align="right" className="tabular-nums">
                    {row.pairs.toLocaleString('en-IN')}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {num(row.model_auc)}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {num(row.pipeline_auc)}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {pct(row.precision)}
                  </TD>
                  <TD mono align="right" className="tabular-nums">
                    {pct(row.recall)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {suggestions && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <p className="micro-label">threshold suggestions</p>
            <StatusChip tone="neutral">suggested, not applied</StatusChip>
          </div>
          <p className="max-w-prose text-xs text-muted">{suggestions.note}</p>
          {suggestions.classes.length === 0 ? (
            <p className="text-xs text-muted">
              No class has {suggestions.min_labels} labelled pairs with both answers yet. Current
              T_HIGH {num(suggestions.current_t_high, 2)}.
            </p>
          ) : (
            <Table>
              <THead>
                <TH>Class</TH>
                <TH align="right">Labelled</TH>
                <TH align="right">Suggested T_HIGH</TH>
                <TH align="right">Precision at it</TH>
                <TH align="right">F1</TH>
                <TH align="right">Current T_HIGH</TH>
                <TH align="right">Precision now</TH>
                <TH>Status</TH>
              </THead>
              <TBody>
                {suggestions.classes.map((row) => (
                  <TR key={row.class_code}>
                    <TD mono>{row.class_code}</TD>
                    <TD mono align="right" className="tabular-nums">
                      {row.labelled_pairs.toLocaleString('en-IN')}
                    </TD>
                    <TD mono align="right" className="tabular-nums">
                      {num(row.suggested_t_high, 4)}
                    </TD>
                    <TD mono align="right" className="tabular-nums">
                      {pct(row.suggested_precision)}
                    </TD>
                    <TD mono align="right" className="tabular-nums">
                      {num(row.suggested_f1)}
                    </TD>
                    <TD mono align="right" className="tabular-nums">
                      {num(row.current_t_high, 2)}
                    </TD>
                    <TD mono align="right" className="tabular-nums">
                      {pct(row.current_precision)}
                    </TD>
                    <TD className="text-xs text-muted">not applied</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      )}
    </div>
  )
}
