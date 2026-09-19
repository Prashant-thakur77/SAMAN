/**
 * The retraining block on /admin: the loop's state, every attempt with its
 * outcome, the per-class numbers, and threshold suggestions that say in so
 * many words that they were not applied.
 */

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RetrainingPanel } from '../components/RetrainingPanel'
import type { LearnStatus } from '../lib/api'

const status: LearnStatus = {
  trained: true,
  model: {
    trained_at: '2026-09-19T10:16:37+00:00',
    n_labels: 455,
    labels: { reviewer: 55, simulated: 400 },
    features: ['tier0_anchor'],
    weights: { tier0_anchor: 0.39 },
    cv: { folds: 5, auc: 0.9978, precision: 0.976, recall: 0.98 },
    holdout: {
      pairs: 4647,
      model_auc: 0.9989,
      pipeline_auc: 0.7017,
      grey_pairs: 698,
      grey_model_auc: 0.9812,
      grey_pipeline_auc: 0.2216,
      per_class: [
        {
          class_code: 'valve.gate',
          pairs: 921,
          positives: 725,
          model_auc: 0.9963,
          pipeline_auc: 0.9972,
          precision: 0.9986,
          recall: 0.9821,
        },
      ],
    },
    path: '/data/models/pairwise.json',
  },
  labels: { reviewer: 55, simulated: 400 },
  labels_since_training: 10,
  min_labels: 40,
  decides: false,
  note: 'Trained on 455 labelled pairs.',
  auto_retrain: {
    enabled: true,
    every: 25,
    labels_since: 10,
    due: false,
    running: false,
  },
  history: [
    {
      ts: '2026-09-19T10:20:00+00:00',
      trigger: 'auto',
      n_labels: 455,
      labels: { reviewer: 55, simulated: 400 },
      cv_auc: 0.998,
      holdout_auc: 0.9989,
      grey_auc: 0.9812,
      holdout_pairs: 4647,
      champion_auc: 0.9989,
      promoted: true,
      reason: 'challenger 0.9989 vs champion 0.9989: not worse by more than 0.005',
      last_label_id: 455,
      weights: { tier0_anchor: 0.39 },
    },
    {
      ts: '2026-09-19T10:18:00+00:00',
      trigger: 'auto',
      n_labels: 430,
      labels: { reviewer: 30, simulated: 400 },
      cv_auc: 0.99,
      holdout_auc: 0.9,
      grey_auc: 0.8,
      holdout_pairs: 4647,
      champion_auc: 0.9986,
      promoted: false,
      reason: 'challenger 0.9 vs champion 0.9986: worse by more than 0.005, champion kept',
      last_label_id: 430,
      weights: null,
    },
  ],
  suggestions: {
    applied: false,
    current_t_high: 0.86,
    min_labels: 30,
    note: 'Suggested, not applied. Thresholds are frozen in match.py.',
    classes: [
      {
        class_code: 'valve.gate',
        labelled_pairs: 94,
        positives: 60,
        suggested_t_high: 0.9234,
        suggested_precision: 0.9828,
        suggested_recall: 1,
        suggested_f1: 0.9913,
        current_t_high: 0.86,
        current_precision: 0.9828,
        current_recall: 1,
        applied: false,
      },
    ],
  },
}

describe('the retraining block', () => {
  it('shows the loop state and every attempt with promoted or kept', () => {
    render(<RetrainingPanel status={status} />)
    const panel = screen.getByTestId('retraining')
    expect(within(panel).getByText('25 reviewer labels')).toBeInTheDocument()
    expect(within(panel).getByText('not yet')).toBeInTheDocument()
    expect(within(panel).getByText('promoted')).toBeInTheDocument()
    expect(within(panel).getByText('kept')).toBeInTheDocument()
    expect(within(panel).getByText(/champion kept/)).toBeInTheDocument()
  })

  it('lists the per-class numbers', () => {
    render(<RetrainingPanel status={status} />)
    expect(screen.getAllByText('valve.gate').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('0.996')).toBeInTheDocument()
    expect(screen.getByText('99.9%')).toBeInTheDocument()
  })

  it('marks threshold suggestions as suggested, not applied', () => {
    render(<RetrainingPanel status={status} />)
    expect(screen.getByText('suggested, not applied')).toBeInTheDocument()
    expect(screen.getByText('0.9234')).toBeInTheDocument()
    expect(screen.getByText('not applied')).toBeInTheDocument()
  })

  it('says so when nothing has been attempted', () => {
    render(
      <RetrainingPanel
        status={{
          ...status,
          history: [],
          suggestions: { ...status.suggestions!, classes: [] },
        }}
      />,
    )
    expect(screen.getByText(/No training attempt recorded yet/)).toBeInTheDocument()
    expect(screen.getByText(/No class has 30 labelled pairs/)).toBeInTheDocument()
  })
})
