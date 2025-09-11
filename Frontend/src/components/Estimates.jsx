// src/components/Estimates.jsx

import React, { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { gsap } from 'gsap'
import {
  FunnelIcon,
  ChevronDownIcon,
  CalendarIcon,
  ArrowPathIcon,
  PlusIcon,
} from '@heroicons/react/24/outline'

// --- Mock Data ---
const estimatesData = [
  {
    job: 'J-1003',
    customer: 'Carlos Ruiz',
    vehicle: 'Porsche 911',
    total: 2315.1,
    status: 'Draft',
    advisor: 'Sergio',
    date: '9/11/2025',
  },
  {
    job: 'J-1001',
    customer: 'John Carter',
    vehicle: 'BMW 328i',
    total: 1240.23,
    status: 'Sent',
    advisor: 'Sergio',
    date: '9/10/2025',
  },
  {
    job: 'J-1002',
    customer: 'Emily Wong',
    vehicle: 'Audi A4',
    total: 842.5,
    status: 'Approved',
    advisor: 'Alex',
    date: '9/9/2025',
  },
  {
    job: 'J-1004',
    customer: 'Lisa Chen',
    vehicle: 'VW GTI',
    total: 410.0,
    status: 'Declined',
    advisor: 'Jordan',
    date: '9/5/2025',
  },
  {
    job: 'J-1005',
    customer: 'Mike Ross',
    vehicle: 'Mercedes C300',
    total: 1850.75,
    status: 'Approved',
    advisor: 'Alex',
    date: '9/4/2025',
  },
]

// --- Helper Components ---
const FilterDropdown = ({ label }) => (
  <div className="relative">
    <select className="w-full bg-background border border-border text-text-secondary text-sm rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-accent">
      <option>{label}</option>
    </select>
    <ChevronDownIcon className="h-4 w-4 text-text-secondary absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
  </div>
)
const FilterDatePicker = ({ label }) => (
  <div className="relative">
    <input
      type="text"
      placeholder={label}
      className="w-full bg-background border border-border text-text-secondary text-sm rounded-lg pl-3 pr-8 py-2.5 focus:outline-none focus:ring-2 focus:ring-accent"
    />
    <CalendarIcon className="h-4 w-4 text-text-secondary absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
  </div>
)

const Estimates = () => {
  const [isFiltersOpen, setIsFiltersOpen] = useState(true)
  const containerRef = useRef(null)
  const headerRef = useRef(null)
  const filtersRef = useRef(null)
  const tableRef = useRef(null)
  const rowRefs = useRef([])

  useEffect(() => {
    // GSAP Animation Timeline
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.fromTo(containerRef.current, { opacity: 0 }, { opacity: 1, duration: 0.5 })
      .fromTo(
        headerRef.current,
        { opacity: 0, y: -30 },
        { opacity: 1, y: 0, duration: 0.6 },
        '-=0.2',
      )
      .fromTo(
        filtersRef.current,
        { opacity: 0, y: -20 },
        { opacity: 1, y: 0, duration: 0.6 },
        '-=0.4',
      )
      .fromTo(tableRef.current, { opacity: 0 }, { opacity: 1, duration: 0.5 })
      .fromTo(
        rowRefs.current,
        { opacity: 0, x: -20 },
        { opacity: 1, x: 0, stagger: 0.05, duration: 0.5 },
        '-=0.3',
      )
  }, [])

  // Animate filter section collapse/expand
  useEffect(() => {
    gsap.to(filtersRef.current, {
      height: isFiltersOpen ? 'auto' : 0,
      opacity: isFiltersOpen ? 1 : 0,
      marginTop: isFiltersOpen ? '1.5rem' : 0,
      duration: 0.4,
      ease: 'power3.inOut',
    })
  }, [isFiltersOpen])

  const getStatusClass = (status) => {
    switch (status) {
      case 'Approved':
        return 'bg-success/20 text-success'
      case 'Sent':
        return 'bg-blue-500/20 text-blue-400'
      case 'Declined':
        return 'bg-danger/20 text-danger'
      case 'Draft':
        return 'bg-gray-500/20 text-text-secondary'
      default:
        return 'bg-surface text-text-secondary'
    }
  }

  return (
    <div ref={containerRef} className="p-4 md:p-8 opacity-0">
      {/* --- Page Header --- */}
      <div ref={headerRef} className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-text-primary">Estimates</h1>
        <div className="flex space-x-3">
          <button className="hidden sm:flex items-center bg-surface border border-border text-text-secondary px-4 py-2 rounded-lg hover:bg-primary-light hover:text-text-primary transition-colors">
            <ArrowPathIcon className="h-4 w-4 mr-2" />
            Reset Filters
          </button>
          <NavLink
            to="/new-estimate"
            className="flex items-center bg-accent hover:bg-accent-dark text-background font-bold py-2 px-4 rounded-lg shadow-lg hover:shadow-xl transform hover:-translate-y-0.5 transition-all duration-300"
          >
            <PlusIcon className="h-5 w-5 mr-1.5" />
            New Estimate
          </NavLink>
        </div>
      </div>

      {/* --- Main Content Card --- */}
      <div className="bg-surface p-4 sm:p-6 rounded-xl border border-border">
        {/* --- Collapsible Filters Section --- */}
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-bold text-text-primary flex items-center">
            <FunnelIcon className="h-5 w-5 mr-2 text-text-secondary" />
            Filters
          </h2>
          <button
            onClick={() => setIsFiltersOpen(!isFiltersOpen)}
            className="text-sm text-primary-light font-semibold"
          >
            {isFiltersOpen ? 'Hide' : 'Show'}
          </button>
        </div>

        <div ref={filtersRef} className="overflow-hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 pt-6">
            <FilterDropdown label="All Statuses" />
            <FilterDatePicker label="Start Date" />
            <FilterDatePicker label="End Date" />
            <FilterDropdown label="All Advisors" />
            <FilterDropdown label="Any Vendor" />
          </div>
        </div>

        {/* --- Table Section --- */}
        <div ref={tableRef} className="mt-6 overflow-x-auto">
          <table className="w-full text-left min-w-[1024px]">
            <thead>
              <tr className="border-b border-border">
                <th className="p-3 text-sm font-semibold text-text-secondary">Job #</th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Customer</th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Vehicle</th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Estimate Total</th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Status</th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Advisor</th>
                <th className="p-3 text-sm font-semibold text-text-secondary flex items-center">
                  Date <ChevronDownIcon className="h-4 w-4 ml-1" />
                </th>
                <th className="p-3 text-sm font-semibold text-text-secondary">Actions</th>
              </tr>
            </thead>
            <tbody>
              {estimatesData.map((est, index) => (
                <tr
                  key={est.job}
                  ref={(el) => (rowRefs.current[index] = el)}
                  className="border-b border-border/50 hover:bg-primary/20 transition-colors duration-200"
                >
                  <td className="p-4 font-mono text-text-secondary text-sm">{est.job}</td>
                  <td className="p-4 text-text-primary font-bold">{est.customer}</td>
                  <td className="p-4 text-text-secondary">{est.vehicle}</td>
                  <td className="p-4 text-text-primary font-mono font-bold">
                    $
                    {est.total.toLocaleString('en-US', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </td>
                  <td className="p-4">
                    <span
                      className={`px-2.5 py-1 text-xs font-bold rounded-full ${getStatusClass(
                        est.status,
                      )}`}
                    >
                      {est.status}
                    </span>
                  </td>
                  <td className="p-4 text-text-secondary">{est.advisor}</td>
                  <td className="p-4 text-text-secondary">{est.date}</td>
                  <td className="p-4 text-sm text-primary-light font-semibold space-x-2 whitespace-nowrap">
                    <a href="#" className="hover:underline">
                      View
                    </a>
                    <span>•</span>
                    <a href="#" className="hover:underline">
                      Edit
                    </a>
                    <span>•</span>
                    <a href="#" className="hover:underline">
                      Resend
                    </a>
                    <span>•</span>
                    <a href="#" className="hover:underline">
                      Duplicate
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default Estimates
