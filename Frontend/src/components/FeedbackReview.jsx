// Feedback Review — the team-facing page that shows advisor feedback on
// estimates (the voice/text the advisor recorded on the Preview step). Newest
// first; the message text is the headline so requirements are readable at a
// glance. Filter by status and mark items reviewed/resolved.
import React, { useEffect, useState, useCallback } from 'react'
import { getEstimateFeedback, updateFeedbackStatus } from '../services/api'

const STATUS_TABS = [
  { key: '', label: 'All' },
  { key: 'new', label: 'New' },
  { key: 'reviewed', label: 'Reviewed' },
  { key: 'resolved', label: 'Resolved' },
]

const STATUS_STYLE = {
  new: 'bg-warning/15 text-warning border-warning/40',
  reviewed: 'bg-info/15 text-info border-info/40',
  resolved: 'bg-success/15 text-success border-success/40',
}

const fmtTime = (iso) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

const FeedbackReview = () => {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    const res = await getEstimateFeedback(filter || undefined)
    setLoading(false)
    if (res.success) { setItems(res.data.items || []); setError(null) }
    else setError(res.error || 'Failed to load')
  }, [filter])

  useEffect(() => { load() }, [load])

  const setStatus = async (id, status) => {
    const res = await updateFeedbackStatus(id, status)
    if (res.success) load()
  }

  return (
    <div className="p-4 md:p-8 min-h-full">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Feedback Review</h1>
          <p className="text-sm text-text-secondary">
            What advisors told us about generated estimates — newest first.
          </p>
        </div>
        <button onClick={load}
          className="text-sm px-3 py-2 rounded-lg border border-border text-text-primary hover:bg-card self-start">
          ↻ Refresh
        </button>
      </div>

      <div className="flex gap-2 mb-5 flex-wrap">
        {STATUS_TABS.map((t) => (
          <button key={t.key} onClick={() => setFilter(t.key)}
            className={`px-3 py-1.5 rounded-full text-sm border ${filter === t.key
              ? 'bg-primary text-background border-primary'
              : 'border-border text-text-secondary hover:bg-card'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading && <p className="text-text-secondary">Loading…</p>}
      {error && <p className="text-error">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <div className="bg-background border border-border rounded-lg p-10 text-center text-text-secondary">
          No feedback yet. It appears here as advisors use the 🎙️ feedback panel on estimates.
        </div>
      )}

      <div className="space-y-3">
        {items.map((f) => (
          <div key={f.feedback_id} className="bg-background border border-border rounded-lg p-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap text-xs text-text-secondary mb-1">
                  <span className={`px-2 py-0.5 rounded-full border ${STATUS_STYLE[f.status] || 'border-border'}`}>
                    {f.status}
                  </span>
                  <span>{f.input_mode === 'voice' ? '🎙️ voice' : '⌨️ typed'}</span>
                  <span>·</span>
                  <span>{fmtTime(f.created_at)}</span>
                </div>
                {/* The headline: exactly what the advisor said. */}
                <p className="text-text-primary text-[15px] leading-relaxed whitespace-pre-wrap">
                  "{f.message}"
                </p>
                <div className="mt-2 text-xs text-text-secondary flex flex-wrap gap-x-3 gap-y-1">
                  {f.vehicle && <span>🚗 {f.vehicle}</span>}
                  {f.service_request && <span>🔧 {f.service_request}</span>}
                  {f.estimate_total != null && <span>💲 ${Number(f.estimate_total).toFixed(2)}</span>}
                  {f.estimate_source && <span>· {f.estimate_source}{f.match_tier ? ` (${f.match_tier})` : ''}</span>}
                  {f.vin && <span className="font-mono">· {f.vin}</span>}
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                {f.status !== 'reviewed' && (
                  <button onClick={() => setStatus(f.feedback_id, 'reviewed')}
                    className="text-xs px-2.5 py-1 rounded border border-info/50 text-info hover:bg-info/10">
                    Mark reviewed
                  </button>
                )}
                {f.status !== 'resolved' && (
                  <button onClick={() => setStatus(f.feedback_id, 'resolved')}
                    className="text-xs px-2.5 py-1 rounded border border-success/50 text-success hover:bg-success/10">
                    Resolve
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default FeedbackReview
