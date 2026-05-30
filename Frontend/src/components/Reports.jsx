// src/components/Reports.jsx
// Six trend charts sourced from /api/v1/analytics/reports?days=N. Each chart
// either renders the live series or an explicit "no data yet" empty state —
// never fake numbers.

import React, { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { ArrowPathIcon } from '@heroicons/react/24/outline'
import { getReportAnalytics } from '../services/api'

const RANGE_OPTIONS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

const ReportsPage = () => {
  const [days, setDays] = useState(7)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = async (d = days) => {
    setLoading(true)
    setError(null)
    const r = await getReportAnalytics(d)
    if (r.success) setData(r.data)
    else setError(r.error)
    setLoading(false)
  }

  useEffect(() => {
    load(days)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days])

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-background text-text-primary font-inter">
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap justify-between items-center gap-3">
          <h1 className="text-2xl md:text-3xl font-bold text-text-primary">Reports</h1>
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-surface border border-border rounded-lg p-1">
              {RANGE_OPTIONS.map((opt) => (
                <button
                  key={opt.days}
                  onClick={() => setDays(opt.days)}
                  className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                    days === opt.days
                      ? 'bg-primary/40 text-text-primary font-semibold'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => load()}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary bg-surface hover:bg-primary/20 border border-border rounded-lg transition-colors disabled:opacity-50"
            >
              <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-surface p-4 rounded-xl border border-danger/40">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card title="Time Saved vs Manual">
            <Trend
              series={data?.time_saved_min}
              dataKey="Minutes"
              valueKey="value"
              color="#B2E742"
              loading={loading}
              emptyText="No approved estimates yet."
            />
          </Card>

          <Card title="Approval Rate Trend">
            <Trend
              series={data?.approval_rate_pct}
              dataKey="Approval %"
              valueKey="value"
              color="#00BFFF"
              loading={loading}
              emptyText="Need decided estimates (approved/declined) to compute approval %."
            />
          </Card>

          <Card title="Average Estimate Value">
            <Trend
              series={data?.average_estimate_usd}
              dataKey="USD"
              valueKey="value"
              color="#FFCC00"
              loading={loading}
              emptyText="No estimates in this range."
              prefix="$"
            />
          </Card>

          <Card title="Vendor Usage (lead share)">
            <Trend
              series={data?.vendor_usage_pct}
              dataKey="Lead vendor %"
              valueKey="value"
              color="#ef4444"
              loading={loading}
              emptyText="No vendor-sourced parts in this range."
              suffix="%"
            />
          </Card>

          <Card title="Cost Savings Trend">
            <Trend
              series={data?.cost_savings_usd}
              dataKey="Savings"
              valueKey="value"
              color="#34d399"
              loading={loading}
              emptyText="Cost savings per estimate are not stored yet — coming with the next pipeline release."
              prefix="$"
            />
          </Card>

          <Card title="Customer Satisfaction">
            <Trend
              series={data?.customer_satisfaction_pct}
              dataKey="Satisfaction %"
              valueKey="value"
              color="#f59e0b"
              loading={loading}
              emptyText="Awaiting customer feedback signal (not collected yet)."
              suffix="%"
            />
          </Card>
        </div>
      </div>
    </div>
  )
}

const Card = ({ title, children }) => (
  <div className="bg-surface rounded-2xl p-6 border border-border flex flex-col">
    <h3 className="text-lg font-bold mb-4 text-text-primary">{title}</h3>
    <div className="flex-1 w-full h-64">{children}</div>
  </div>
)

const Trend = ({ series, dataKey, valueKey, color, loading, emptyText, prefix = '', suffix = '' }) => {
  if (loading) {
    return <div className="h-full w-full rounded-md bg-background/60 animate-pulse" />
  }
  if (!series || series.length === 0) {
    return <Empty text={emptyText} />
  }
  const allNull = series.every((p) => p[valueKey] == null)
  if (allNull) {
    return <Empty text={emptyText} />
  }
  const chartData = series.map((p) => ({ name: p.label, [dataKey]: p[valueKey] ?? 0 }))
  return (
    <ResponsiveContainer width="99%" height={256}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis dataKey="name" stroke="var(--color-text-secondary)" />
        <YAxis stroke="var(--color-text-secondary)" tickFormatter={(v) => `${prefix}${v}${suffix}`} />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
          }}
          labelStyle={{ color: 'var(--color-text-primary)' }}
          formatter={(v) => `${prefix}${v}${suffix}`}
        />
        <Legend />
        <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

const Empty = ({ text }) => (
  <div className="flex items-center justify-center h-full">
    <p className="text-sm text-text-secondary text-center max-w-xs">{text}</p>
  </div>
)

export default ReportsPage
