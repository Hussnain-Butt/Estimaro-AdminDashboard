// src/components/Dashboard.jsx
// Live KPIs + trends sourced from /api/v1/analytics/dashboard.

import React, { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line, Bar } from 'react-chartjs-2'
import {
  ClockIcon,
  CheckCircleIcon,
  WrenchScrewdriverIcon,
  TruckIcon,
  BellAlertIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
} from '@heroicons/react/24/outline'
import { getDashboardAnalytics } from '../services/api'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
)

const STAT_ICON = {
  estimates_today: WrenchScrewdriverIcon,
  approval_rate: CheckCircleIcon,
  time_saved: ClockIcon,
  parts_sourcing: TruckIcon,
}

const STAT_COLOR = {
  estimates_today: 'text-blue-400',
  approval_rate: 'text-accent',
  time_saved: 'text-yellow-400',
  parts_sourcing: 'text-purple-400',
}

const ALERT_ICON = {
  warning: ExclamationTriangleIcon,
  info: BellAlertIcon,
}

const Dashboard = () => {
  const containerRef = useRef(null)
  const cardsRef = useRef([])
  const sectionsRef = useRef([])
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const animatedRef = useRef(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    const r = await getDashboardAnalytics()
    if (r.success) {
      setData(r.data)
    } else {
      setError(r.error)
    }
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  // Fade the wrapper in once data first arrives; numeric count-up runs
  // only the first time so subsequent refreshes don't flicker.
  useEffect(() => {
    if (!data || animatedRef.current) return
    animatedRef.current = true
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.fromTo(containerRef.current, { opacity: 0 }, { opacity: 1, duration: 0.5 })
      .fromTo(
        cardsRef.current.filter(Boolean),
        { opacity: 0, y: 40 },
        { opacity: 1, y: 0, stagger: 0.08, duration: 0.5 },
        '-=0.2',
      )
      .fromTo(
        sectionsRef.current.filter(Boolean),
        { opacity: 0, y: 40 },
        { opacity: 1, y: 0, stagger: 0.12, duration: 0.5 },
        '-=0.3',
      )

    cardsRef.current.filter(Boolean).forEach((card, index) => {
      const stat = data.stats[index]
      if (stat && typeof stat.value === 'number') {
        const valueEl = card.querySelector('.stat-value')
        if (!valueEl) return
        const startValue = { val: 0 }
        gsap.to(startValue, {
          val: stat.value,
          duration: 1.2,
          ease: 'power2.out',
          delay: 0.3,
          onUpdate: () => {
            valueEl.textContent = Math.round(startValue.val)
          },
        })
      }
    })
  }, [data])

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'var(--color-surface)',
        titleColor: 'var(--color-text-primary)',
        bodyColor: 'var(--color-text-secondary)',
        borderColor: 'var(--color-border)',
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
      },
    },
    scales: {
      x: {
        ticks: { color: 'var(--color-text-secondary)', font: { family: 'Inter' } },
        grid: { color: 'var(--color-border)' },
      },
      y: {
        beginAtZero: true,
        ticks: { color: 'var(--color-text-secondary)', font: { family: 'Inter' } },
        grid: { color: 'var(--color-border)' },
      },
    },
    interaction: { intersect: false, mode: 'index' },
  }

  const weekly = data?.weekly_activity || []
  const lineChartData = {
    labels: weekly.map((d) => d.label),
    datasets: [
      {
        label: 'Estimates',
        data: weekly.map((d) => d.estimates),
        borderColor: 'var(--color-primary-light)',
        backgroundColor: 'rgba(74, 110, 173, 0.2)',
        pointBackgroundColor: 'var(--color-primary-light)',
        pointBorderColor: 'var(--color-surface)',
        pointHoverRadius: 7,
        pointHoverBackgroundColor: 'var(--color-primary-light)',
        fill: true,
        tension: 0.4,
      },
    ],
  }

  const advisorApproval = data?.advisor_approval || []
  const barChartData = {
    labels: advisorApproval.map((a) => a.advisor),
    datasets: [
      {
        label: 'Approval %',
        data: advisorApproval.map((a) => a.approval_pct),
        backgroundColor: 'var(--color-accent)',
        borderRadius: 4,
        barThickness: 30,
      },
    ],
  }

  if (loading && !data) {
    return (
      <div className="p-4 md:p-6 lg:p-8 space-y-8">
        <div className="h-8 w-48 bg-surface rounded animate-pulse" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="bg-surface p-5 rounded-xl border border-border h-28 animate-pulse" />
          ))}
        </div>
        <div className="bg-surface p-6 rounded-xl border border-border h-80 animate-pulse" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 lg:p-8">
        <div className="bg-surface p-6 rounded-xl border border-danger/40 flex items-center justify-between">
          <div>
            <p className="font-semibold text-danger">Failed to load dashboard</p>
            <p className="text-sm text-text-secondary mt-1">{error}</p>
          </div>
          <button
            onClick={load}
            className="px-4 py-2 bg-primary/40 hover:bg-primary/60 rounded-lg text-text-primary text-sm font-semibold"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const stats = data.stats || []
  const alerts = data.alerts || []
  const recent = data.recent_estimates || []

  return (
    <div ref={containerRef} className="p-4 md:p-6 lg:p-8 space-y-8 opacity-0">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl md:text-3xl font-bold text-text-primary">Dashboard</h1>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary bg-surface hover:bg-primary/20 border border-border rounded-lg transition-colors disabled:opacity-50"
        >
          <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, index) => {
          const Icon = STAT_ICON[stat.key] || WrenchScrewdriverIcon
          const color = STAT_COLOR[stat.key] || 'text-blue-400'
          return (
            <div
              key={stat.key}
              ref={(el) => (cardsRef.current[index] = el)}
              className="bg-surface p-5 rounded-xl border border-border transition-all duration-300 hover:border-accent hover:-translate-y-1 hover:shadow-2xl hover:shadow-accent/10"
            >
              <div className="flex justify-between items-center">
                <div className="flex flex-col space-y-1">
                  <p className="text-sm text-text-secondary">{stat.title}</p>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-3xl font-bold text-text-primary stat-value">
                      {stat.value}
                    </span>
                    {stat.suffix && (
                      <span className="text-xl font-semibold text-text-secondary">{stat.suffix}</span>
                    )}
                  </div>
                </div>
                <div className="bg-primary/30 p-3 rounded-lg">
                  <Icon className={`h-6 w-6 ${color}`} />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Charts + activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        <div className="lg:col-span-3 space-y-8">
          <div
            ref={(el) => (sectionsRef.current[0] = el)}
            className="bg-surface p-6 rounded-xl border border-border h-80"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Weekly Activity</h3>
            {weekly.length === 0 ? (
              <EmptyState text="No estimates in the last 7 days yet." />
            ) : (
              <Line options={chartOptions} data={lineChartData} />
            )}
          </div>
          <div
            ref={(el) => (sectionsRef.current[1] = el)}
            className="bg-surface p-6 rounded-xl border border-border h-80"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Approval % by Advisor</h3>
            {advisorApproval.length === 0 ? (
              <EmptyState text="Need at least one decided estimate per advisor to compute approval %." />
            ) : (
              <Bar options={chartOptions} data={barChartData} />
            )}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-8">
          <div
            ref={(el) => (sectionsRef.current[2] = el)}
            className="bg-surface p-6 rounded-xl border border-border"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Alerts</h3>
            {alerts.length === 0 ? (
              <p className="text-sm text-text-secondary py-2">All clear — no alerts.</p>
            ) : (
              <div className="space-y-4">
                {alerts.map((alert, idx) => {
                  const Icon = ALERT_ICON[alert.level] || BellAlertIcon
                  const isWarn = alert.level === 'warning'
                  return (
                    <div
                      key={idx}
                      className={`flex items-start p-3 rounded-lg ${
                        isWarn ? 'bg-warning/10' : 'bg-primary/20'
                      }`}
                    >
                      <Icon
                        className={`h-5 w-5 mt-0.5 mr-3 flex-shrink-0 ${
                          isWarn ? 'text-warning' : 'text-blue-400'
                        }`}
                      />
                      <p className="text-sm text-text-secondary">{alert.text}</p>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div
            ref={(el) => (sectionsRef.current[3] = el)}
            className="bg-surface p-6 rounded-xl border border-border"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Recent Estimates</h3>
            {recent.length === 0 ? (
              <p className="text-sm text-text-secondary py-2">No estimates yet. Create one from “New Estimate”.</p>
            ) : (
              <div className="space-y-3">
                {recent.map((est) => (
                  <div
                    key={est.id}
                    className="flex justify-between items-center hover:bg-primary/20 p-2 rounded-md transition-colors duration-200"
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      <div className="bg-background p-2 rounded-md font-mono text-xs text-text-secondary uppercase">
                        {est.status}
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-text-primary text-sm truncate">{est.customer}</p>
                        <p className="text-xs text-text-secondary truncate">{est.vehicle}</p>
                      </div>
                    </div>
                    <p className="font-semibold text-text-primary font-mono text-sm whitespace-nowrap ml-3">
                      ${est.total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const EmptyState = ({ text }) => (
  <div className="flex items-center justify-center h-full">
    <p className="text-sm text-text-secondary text-center max-w-xs">{text}</p>
  </div>
)

export default Dashboard
