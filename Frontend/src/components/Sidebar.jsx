// src/components/Sidebar.jsx

import React, { useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { gsap } from 'gsap'
import {
  ChartBarIcon,
  PlusIcon,
  DocumentTextIcon,
  UserGroupIcon,
  TagIcon,
  PresentationChartLineIcon,
  Cog6ToothIcon,
} from '@heroicons/react/24/outline'
import logo from '../assets/logo.jpg' // सुनिश्चित करें कि आपका लोगो src/assets/ में है

const navLinks = [
  { text: 'Dashboard', path: '/', icon: ChartBarIcon },
  { text: 'New Estimate', path: '/new-estimate', icon: PlusIcon },
  { text: 'Estimates', path: '/estimates', icon: DocumentTextIcon },
  { text: 'Customers', path: '/customers', icon: UserGroupIcon },
  { text: 'Vendors', path: '/vendors', icon: TagIcon },
  { text: 'Reports', path: '/reports', icon: PresentationChartLineIcon },
]

const Sidebar = () => {
  const sidebarRef = useRef(null)
  const linkRefs = useRef([])

  useEffect(() => {
    const sidebar = sidebarRef.current
    gsap.fromTo(
      sidebar,
      { x: -288 }, // w-72 के बराबर
      { x: 0, duration: 0.8, ease: 'power3.out' },
    )
    gsap.fromTo(
      linkRefs.current,
      { opacity: 0, x: -50 },
      {
        opacity: 1,
        x: 0,
        duration: 0.5,
        ease: 'power3.out',
        stagger: 0.1,
        delay: 0.3,
      },
    )
  }, [])

  const navLinkClass = ({ isActive }) =>
    `flex items-center w-full p-3 my-1 rounded-lg transition-all duration-300 ease-in-out group ${
      isActive
        ? 'bg-primary text-text-primary shadow-lg'
        : 'text-text-secondary hover:bg-primary-light hover:text-text-primary'
    }`

  return (
    <aside
      ref={sidebarRef}
      className="w-72 flex-shrink-0 bg-surface p-6 flex flex-col justify-between border-r border-border h-screen"
    >
      <div className="flex flex-col">
        {/* Logo and Title Section */}
        <div className="flex items-center space-x-4 mb-12">
          <img src={logo} alt="German Sport Logo" className="h-12 w-12 rounded-full" />
          <div>
            <h1 className="text-text-primary text-xl font-bold">German Sport</h1>
            <p className="text-sm text-text-secondary">Estimaro</p>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="flex-grow">
          <ul>
            {navLinks.map((link, index) => (
              <li key={link.text} ref={(el) => (linkRefs.current[index] = el)}>
                <NavLink to={link.path} className={navLinkClass}>
                  <link.icon
                    className={`h-6 w-6 mr-4 transition-transform duration-300 group-hover:scale-110`}
                  />
                  <span className="font-semibold">{link.text}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      {/* Bottom Section */}
      <div className="border-t border-border pt-6 space-y-4">
        {/* Settings Link */}
        <NavLink to="/settings" className={navLinkClass}>
          <Cog6ToothIcon className="h-6 w-6 mr-4 transition-transform duration-300 group-hover:scale-110" />
          <span className="font-semibold">Settings</span>
        </NavLink>

        {/* New Estimate Button */}
        <button className="w-full bg-accent hover:bg-accent-dark text-background font-bold py-3 px-4 rounded-lg shadow-lg hover:shadow-xl transform hover:-translate-y-1 transition-all duration-300 ease-in-out flex items-center justify-center">
          <PlusIcon className="h-5 w-5 mr-2" />
          <span>New Estimate</span>
        </button>
      </div>
    </aside>
  )
}

export default Sidebar
