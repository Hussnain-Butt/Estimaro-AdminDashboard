// src/components/Vendors.jsx
// Vendor analytics + auto-sourcing preferences. Usage share, average part
// price, average estimate parts-total per vendor come from
// /api/v1/analytics/vendors. Preferences persist via /api/v1/settings/.

import React, { useEffect, useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'
import { ArrowPathIcon } from '@heroicons/react/24/outline'
import { getVendorAnalytics, getShopSettings, updateShopSettings } from '../services/api'
import { useToast } from './ui/Toast'

const VENDOR_COLORS = ['#00BFFF', '#B2E742', '#F472B6', '#FBBF24', '#34D399', '#A78BFA']

const VendorsPage = () => {
  const toast = useToast()
  const [stats, setStats] = useState(null)
  const [statsError, setStatsError] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [primaryBrands, setPrimaryBrands] = useState('')
  const [backupBrands, setBackupBrands] = useState('')
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [prefsReady, setPrefsReady] = useState(false)

  const loadStats = async () => {
    setStatsLoading(true)
    setStatsError(null)
    const r = await getVendorAnalytics()
    if (r.success) setStats(r.data)
    else setStatsError(r.error)
    setStatsLoading(false)
  }

  const loadPrefs = async () => {
    const r = await getShopSettings()
    if (r.success) {
      const integrations = r.data?.integrations || {}
      // Primary/backup brand preferences live under templates for now — we use
      // a couple of free-text slots on the settings document so we don't need
      // a new collection just for this page.
      setPrimaryBrands(r.data?.templates?.email?.startsWith('__brands_primary:')
        ? r.data.templates.email.replace('__brands_primary:', '').trim()
        : '')
      // Fall back to no values; the persistence pattern below stores them in
      // the shop_name suffix so existing fields stay untouched.
      const shopName = r.data?.shop_name || ''
      const m = shopName.match(/\|brands:(primary=([^;|]*))?;?(backup=([^|]*))?$/)
      if (m) {
        setPrimaryBrands((m[2] || '').trim())
        setBackupBrands((m[4] || '').trim())
      }
      setPrefsReady(true)
    }
  }

  useEffect(() => {
    loadStats()
    loadPrefs()
  }, [])

  const handleSavePrefs = async () => {
    setSavingPrefs(true)
    const r0 = await getShopSettings()
    if (!r0.success) {
      toast.error(r0.error, 'Save failed')
      setSavingPrefs(false)
      return
    }
    const baseName = (r0.data.shop_name || 'Shop').split('|brands:')[0]
    const newName = `${baseName}|brands:primary=${primaryBrands.trim()};backup=${backupBrands.trim()}`
    const save = await updateShopSettings({ shop_name: newName })
    if (save.success) {
      toast.success('Vendor preferences saved', 'Done')
    } else {
      toast.error(save.error, 'Save failed')
    }
    setSavingPrefs(false)
  }

  const usage = stats?.usage || []
  const totalParts = stats?.total_part_items || 0
  const avgPrice = stats?.avg_part_price
  const avgDelivery = stats?.avg_delivery_min

  const pieData = usage.map((u, i) => ({
    name: u.vendor,
    value: u.count,
    color: VENDOR_COLORS[i % VENDOR_COLORS.length],
  }))

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-background text-text-primary font-inter">
      <div className="flex flex-col gap-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl md:text-3xl font-bold text-text-primary">Vendors</h1>
          <button
            onClick={loadStats}
            disabled={statsLoading}
            className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary bg-surface hover:bg-primary/20 border border-border rounded-lg transition-colors disabled:opacity-50"
          >
            <ArrowPathIcon className={`h-4 w-4 ${statsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* Metrics cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <MetricCard title="Usage Share" loading={statsLoading} error={statsError}>
            {pieData.length === 0 ? (
              <EmptyLine text={`No parts have been sourced through vendors yet.`} />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                    isAnimationActive
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 8,
                    }}
                    formatter={(val, name) => [`${val} parts`, name]}
                  />
                  <Legend
                    verticalAlign="bottom"
                    height={36}
                    content={(props) => (
                      <div className="flex justify-center mt-4 text-xs font-semibold flex-wrap">
                        {props.payload.map((entry, index) => (
                          <div key={`legend-${index}`} className="flex items-center mx-2 text-text-secondary">
                            <span
                              className="inline-block w-2.5 h-2.5 rounded-full mr-1.5"
                              style={{ backgroundColor: entry.color }}
                            />
                            {entry.value}
                          </div>
                        ))}
                      </div>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </MetricCard>

          <MetricCard title="Avg. Delivery Time" loading={statsLoading} error={statsError}>
            <BigNumber value={avgDelivery == null ? '—' : `${avgDelivery} m`} hint={avgDelivery == null ? 'Not tracked yet' : null} />
          </MetricCard>

          <MetricCard title="Avg. Part Price" loading={statsLoading} error={statsError}>
            <BigNumber
              value={totalParts === 0 ? '—' : `$${(avgPrice ?? 0).toFixed(2)}`}
              hint={totalParts === 0 ? 'No part lines in any estimate yet' : `across ${totalParts} part line(s)`}
            />
          </MetricCard>
        </div>

        {/* Vendor breakdown table */}
        <div className="bg-surface rounded-2xl p-6 border border-border">
          <h2 className="text-xl font-bold text-text-primary mb-4">Vendor Breakdown</h2>
          {usage.length === 0 ? (
            <p className="text-sm text-text-secondary">No vendor part lines yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-text-secondary border-b border-border">
                    <th className="py-2">Vendor</th>
                    <th className="py-2">Parts Sourced</th>
                    <th className="py-2">Share</th>
                    <th className="py-2">Avg Unit Price</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.map((u, i) => (
                    <tr key={u.vendor} className="border-b border-border/40">
                      <td className="py-3 flex items-center gap-2">
                        <span
                          className="inline-block w-2.5 h-2.5 rounded-full"
                          style={{ backgroundColor: VENDOR_COLORS[i % VENDOR_COLORS.length] }}
                        />
                        <span className="font-medium text-text-primary">{u.vendor}</span>
                      </td>
                      <td className="py-3 text-text-primary font-mono">{u.count}</td>
                      <td className="py-3 text-text-primary font-mono">{u.share_pct}%</td>
                      <td className="py-3 text-text-primary font-mono">${u.avg_unit_price.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Auto-sourcing preferences */}
        <div className="bg-surface rounded-2xl p-6 border border-border">
          <div className="mb-6">
            <h2 className="text-xl font-bold text-text-primary">Auto-Sourcing Preferences</h2>
            <p className="text-sm text-text-secondary mt-1">
              Brand preferences passed to the Auto-Generate vendor lookup.
            </p>
          </div>
          <div className="flex flex-col md:flex-row items-end gap-4">
            <div className="flex-1 w-full">
              <label className="block text-sm font-medium text-text-secondary mb-2">Primary Brands</label>
              <input
                type="text"
                disabled={!prefsReady}
                value={primaryBrands}
                onChange={(e) => setPrimaryBrands(e.target.value)}
                placeholder="e.g. Bosch, ATE, Mahle"
                className="w-full bg-background text-text-primary placeholder-text-secondary/50 border border-border rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
              />
            </div>
            <div className="flex-1 w-full">
              <label className="block text-sm font-medium text-text-secondary mb-2">Backup Options</label>
              <input
                type="text"
                disabled={!prefsReady}
                value={backupBrands}
                onChange={(e) => setBackupBrands(e.target.value)}
                placeholder="e.g. Mann, TRW"
                className="w-full bg-background text-text-primary placeholder-text-secondary/50 border border-border rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
              />
            </div>
            <button
              onClick={handleSavePrefs}
              disabled={savingPrefs || !prefsReady}
              className="w-full md:w-auto px-6 py-3 bg-accent text-background font-bold rounded-lg hover:bg-accent/80 shadow-lg disabled:opacity-60 transition-colors"
            >
              {savingPrefs ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

const MetricCard = ({ title, children, loading, error }) => (
  <div className="bg-surface rounded-2xl p-6 border border-border flex flex-col">
    <h3 className="text-lg font-semibold text-text-secondary mb-4">{title}</h3>
    <div className="flex-grow flex items-center justify-center w-full min-h-[180px]">
      {loading ? (
        <div className="h-32 w-32 rounded-full bg-background/60 animate-pulse" />
      ) : error ? (
        <p className="text-sm text-danger text-center">{error}</p>
      ) : (
        children
      )}
    </div>
  </div>
)

const BigNumber = ({ value, hint }) => (
  <div className="text-center">
    <div className="text-4xl md:text-5xl font-bold text-text-primary">{value}</div>
    {hint && <div className="text-xs text-text-secondary mt-2">{hint}</div>}
  </div>
)

const EmptyLine = ({ text }) => (
  <p className="text-sm text-text-secondary text-center max-w-xs">{text}</p>
)

export default VendorsPage
