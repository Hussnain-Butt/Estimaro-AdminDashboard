// Human-in-loop review queue (proposal Layer 6 follow-through).
//
// Lists auto-generated estimates that the worker flagged as needing review:
// confidence.tier ∈ {advisor_review, manual_review}. Reads from the same
// /auto-generate/jobs endpoint the polling code uses, so no new backend
// surface is required — the filter is just a client-side reduce. Each row
// links into NewEstimate prefilled with the job's saved state so the
// advisor can finish or correct it.
import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExclamationTriangleIcon, ShieldCheckIcon, ClockIcon } from '@heroicons/react/24/outline'
import api from '../services/api'

const tierStyle = (tier) => {
  if (tier === 'manual_review') return {
    chip: 'bg-danger/15 text-danger border-danger/40',
    icon: <ExclamationTriangleIcon className="h-3.5 w-3.5" />,
    label: 'Manual review',
  }
  if (tier === 'advisor_review') return {
    chip: 'bg-warning/15 text-warning border-warning/40',
    icon: <ShieldCheckIcon className="h-3.5 w-3.5" />,
    label: 'Advisor review',
  }
  return {
    chip: 'bg-surface text-text-secondary border-border',
    icon: <ClockIcon className="h-3.5 w-3.5" />,
    label: tier || 'unknown',
  }
}

const fmtTime = (iso) => {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMin = Math.round((now - d) / 60000)
    if (diffMin < 60) return `${diffMin}m ago`
    if (diffMin < 24 * 60) return `${Math.round(diffMin / 60)}h ago`
    return d.toLocaleDateString()
  } catch {
    return ''
  }
}

const ReviewQueue = () => {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all') // all | advisor_review | manual_review

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/auto-generate/jobs', {
          params: { status_filter: 'completed' },
        })
        if (cancelled) return
        setJobs(Array.isArray(res.data) ? res.data : [])
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || e.message || 'Failed to load')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    // Poll every 30s so newly finished jobs trickle in without manual refresh.
    const t = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  const filteredJobs = useMemo(() => {
    const needsReview = jobs.filter(j => {
      const tier = j?.result?.confidence?.tier
      return tier === 'advisor_review' || tier === 'manual_review'
    })
    if (filter === 'all') return needsReview
    return needsReview.filter(j => j?.result?.confidence?.tier === filter)
  }, [jobs, filter])

  const counts = useMemo(() => {
    const out = { advisor_review: 0, manual_review: 0 }
    for (const j of jobs) {
      const tier = j?.result?.confidence?.tier
      if (tier in out) out[tier]++
    }
    return out
  }, [jobs])

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Review Queue</h1>
          <p className="text-sm text-text-secondary mt-1">
            Auto-generated estimates the AI flagged as needing a second look — sourcing was thin,
            verification was uncertain, or extraction confidence was low.
          </p>
        </div>
        <div className="flex gap-2 text-sm">
          {[
            { key: 'all',             label: `All (${counts.advisor_review + counts.manual_review})` },
            { key: 'advisor_review',  label: `Advisor (${counts.advisor_review})` },
            { key: 'manual_review',   label: `Manual (${counts.manual_review})` },
          ].map(opt => (
            <button
              key={opt.key}
              onClick={() => setFilter(opt.key)}
              className={`px-3 py-1.5 rounded-full border text-xs transition-colors ${
                filter === opt.key
                  ? 'bg-accent/20 border-accent text-accent'
                  : 'bg-surface border-border text-text-secondary hover:border-accent/50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/30 text-danger p-4 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading && jobs.length === 0 ? (
        <div className="bg-surface p-8 rounded-lg border border-border text-center text-text-secondary">
          Loading queue…
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="bg-surface p-12 rounded-lg border border-border text-center">
          <ShieldCheckIcon className="h-12 w-12 mx-auto text-success/70 mb-3" />
          <p className="text-text-primary font-semibold">All clear</p>
          <p className="text-text-secondary text-sm mt-1">
            No estimates need review right now. Auto-approved jobs go straight to the Estimates list.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredJobs.map(job => {
            const r = job.result || {}
            const conf = r.confidence || {}
            const tier = conf.tier
            const score = conf.score != null ? Math.round(conf.score * 100) : null
            const breakdown = conf.breakdown || {}
            const ts = tierStyle(tier)
            const v = r.vehicleInfo || {}
            const consensus = r.consensus || {}
            const consensusGroups = Object.values(consensus)
            const worstSources = consensusGroups.reduce((acc, g) => {
              const priced = g.vendors_with_price || 0
              const total = g.vendors_total || 0
              if (acc == null || priced < acc.priced) return { priced, total, outliers: (g.outliers || []).length }
              return acc
            }, null)

            const labor = r.laborItems?.[0]
            const partsCount = (r.partsItems || []).length

            return (
              <div
                key={job.job_id}
                className="bg-surface border border-border rounded-lg p-4 hover:border-accent/40 transition-colors"
              >
                <div className="flex justify-between items-start gap-4 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs ${ts.chip}`}>
                        {ts.icon}
                        {ts.label}
                        {score != null && <span className="font-mono">· {score}%</span>}
                      </span>
                      {worstSources && (
                        <span className="text-xs text-text-secondary">
                          Sources {worstSources.priced}/{worstSources.total}
                          {worstSources.outliers > 0 && (
                            <span className="text-warning ml-1">· {worstSources.outliers} outlier</span>
                          )}
                        </span>
                      )}
                      <span className="text-xs text-text-secondary">
                        {fmtTime(job.completed_at || job.created_at)}
                      </span>
                    </div>
                    <p className="text-text-primary font-semibold truncate">
                      {v.year} {v.make} {v.model}
                      {labor && (
                        <span className="text-text-secondary font-normal ml-2">
                          — {labor.description}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-text-secondary mt-1 flex gap-4 flex-wrap">
                      {labor && <span>{labor.hours}h labor</span>}
                      <span>{partsCount} part{partsCount === 1 ? '' : 's'}</span>
                      {r.breakdown?.total != null && (
                        <span className="font-medium text-text-primary">
                          ${parseFloat(r.breakdown.total).toFixed(2)}
                        </span>
                      )}
                    </p>
                    {(breakdown.extraction != null || breakdown.verification != null || breakdown.sourcing != null) && (
                      <p className="text-[11px] text-text-secondary mt-1.5 font-mono">
                        Extraction {Math.round((breakdown.extraction || 0) * 100)}% ·
                        Verification {Math.round((breakdown.verification || 0) * 100)}% ·
                        Sourcing {Math.round((breakdown.sourcing || 0) * 100)}%
                        {breakdown.sourcing_note && (
                          <span className="ml-2 not-italic text-warning">
                            ({breakdown.sourcing_note.replace(/_/g, ' ')})
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                  <Link
                    to={`/new-estimate?reviewJob=${job.job_id}`}
                    className="bg-accent text-background px-3 py-1.5 rounded-md text-sm font-semibold hover:bg-accent/80 transition-colors whitespace-nowrap"
                  >
                    Open
                  </Link>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default ReviewQueue
