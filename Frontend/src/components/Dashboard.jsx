// src/components/Dashboard.jsx

import React, { useEffect, useRef } from 'react'
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
} from '@heroicons/react/24/outline'

// Register all necessary Chart.js components
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

// --- Data ---

const stats = [
  { title: 'Estimates Today', value: 1, icon: WrenchScrewdriverIcon, color: 'text-blue-400' },
  { title: 'Approval Rate', suffix: '%', value: 25, icon: CheckCircleIcon, color: 'text-accent' },
  { title: 'Time Saved', suffix: 'm', value: 50, icon: ClockIcon, color: 'text-yellow-400' },
  {
    title: 'Parts Sourcing',
    value: 'Worldpac 2 • SSF 2',
    icon: TruckIcon,
    color: 'text-purple-400',
  },
]

const recentEstimates = [
  { job: 'J-1001', customer: 'John Carter', vehicle: 'BMW 328i', total: 1240.23 },
  { job: 'J-1002', customer: 'Emily Wong', vehicle: 'Audi A4', total: 842.5 },
  { job: 'J-1003', customer: 'Carlos Ruiz', vehicle: 'Porsche 911', total: 2315.1 },
  { job: 'J-1004', customer: 'Lisa Chen', vehicle: 'VW GTI', total: 410.0 },
]

const alerts = [
  { text: '3 estimates awaiting approval', icon: BellAlertIcon, level: 'info' },
  {
    text: '1 part out of stock — alternative available',
    icon: ExclamationTriangleIcon,
    level: 'warning',
  },
]

// --- Main Component ---

const Dashboard = () => {
  const containerRef = useRef(null)
  const cardsRef = useRef([])
  const sectionsRef = useRef([])

  // --- Chart Configuration ---

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
        ticks: { color: 'var(--color-text-secondary)', font: { family: 'Inter' } },
        grid: { color: 'var(--color-border)' },
      },
    },
    interaction: {
      intersect: false,
      mode: 'index',
    },
  }

  const lineChartData = {
    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    datasets: [
      {
        label: 'Estimates',
        data: [3, 2, 4, 3, 5, 6, 5],
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

  const barChartData = {
    labels: ['Sergio', 'Alex', 'Jordan'],
    datasets: [
      {
        label: 'Approval %',
        data: [85, 72, 64],
        backgroundColor: 'var(--color-accent)',
        borderRadius: 4,
        barThickness: 30,
      },
    ],
  }

  useEffect(() => {
    // GSAP Animation Timeline
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })

    tl.fromTo(containerRef.current, { opacity: 0 }, { opacity: 1, duration: 0.5 })
      .fromTo(
        cardsRef.current,
        { opacity: 0, y: 50 },
        { opacity: 1, y: 0, stagger: 0.1, duration: 0.6 },
        '-=0.2',
      )
      .fromTo(
        sectionsRef.current,
        { opacity: 0, y: 50 },
        { opacity: 1, y: 0, stagger: 0.15, duration: 0.6 },
        '-=0.4',
      )

    // Number count-up animation for stats
    // We filter out any null/undefined entries just to be safe
    cardsRef.current.filter(Boolean).forEach((card, index) => {
      const stat = stats[index]
      // This check prevents the crash if stat is undefined
      if (stat && typeof stat.value === 'number') {
        const valueEl = card.querySelector('.stat-value')
        let startValue = { val: 0 }
        gsap.to(startValue, {
          val: stat.value,
          duration: 1.5,
          ease: 'power2.out',
          delay: 0.5,
          onUpdate: () => {
            valueEl.textContent = Math.round(startValue.val)
          },
        })
      }
    })
  }, [])

  return (
    <div ref={containerRef} className="p-4 md:p-6 lg:p-8 space-y-8 opacity-0">
      {/* --- Header --- */}
      <div className="flex justify-between items-center">
        <h1 className="text-2xl md:text-3xl font-bold text-text-primary">Dashboard</h1>
      </div>

      {/* --- Statistic Cards --- */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, index) => (
          <div
            key={stat.title}
            // FIX: Assign ref by index instead of pushing
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
                <stat.icon className={`h-6 w-6 ${stat.color}`} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* --- Main Grid Layout --- */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        {/* --- Left Column: Charts (takes 3/5 width on large screens) --- */}
        <div className="lg:col-span-3 space-y-8">
          <div
            ref={(el) => (sectionsRef.current[0] = el)}
            className="bg-surface p-6 rounded-xl border border-border h-80"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Weekly Activity</h3>
            <Line options={chartOptions} data={lineChartData} />
          </div>
          <div
            ref={(el) => (sectionsRef.current[1] = el)}
            className="bg-surface p-6 rounded-xl border border-border h-80"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Approval % by Advisor</h3>
            <Bar options={chartOptions} data={barChartData} />
          </div>
        </div>

        {/* --- Right Column: Activity Feed (takes 2/5 width on large screens) --- */}
        <div className="lg:col-span-2 space-y-8">
          <div
            ref={(el) => (sectionsRef.current[2] = el)}
            className="bg-surface p-6 rounded-xl border border-border"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Alerts</h3>
            <div className="space-y-4">
              {alerts.map((alert) => (
                <div
                  key={alert.text}
                  className={`flex items-start p-3 rounded-lg ${
                    alert.level === 'warning' ? 'bg-warning/10' : 'bg-primary/20'
                  }`}
                >
                  <alert.icon
                    className={`h-5 w-5 mt-0.5 mr-3 flex-shrink-0 ${
                      alert.level === 'warning' ? 'text-warning' : 'text-blue-400'
                    }`}
                  />
                  <p className="text-sm text-text-secondary">{alert.text}</p>
                </div>
              ))}
            </div>
          </div>

          <div
            ref={(el) => (sectionsRef.current[3] = el)}
            className="bg-surface p-6 rounded-xl border border-border"
          >
            <h3 className="text-lg font-bold text-text-primary mb-4">Recent Estimates</h3>
            <div className="space-y-3">
              {recentEstimates.map((est) => (
                <div
                  key={est.job}
                  className="flex justify-between items-center hover:bg-primary/20 p-2 rounded-md transition-colors duration-200"
                >
                  <div className="flex items-center space-x-3">
                    <div className="bg-background p-2 rounded-md font-mono text-xs text-text-secondary">
                      {est.job}
                    </div>
                    <div>
                      <p className="font-semibold text-text-primary text-sm">{est.customer}</p>
                      <p className="text-xs text-text-secondary">{est.vehicle}</p>
                    </div>
                  </div>
                  <p className="font-semibold text-text-primary font-mono text-sm">
                    $
                    {est.total.toLocaleString('en-US', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
