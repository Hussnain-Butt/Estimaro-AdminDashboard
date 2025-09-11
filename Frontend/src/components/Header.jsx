// src/components/Header.jsx

import React, { useState, useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { gsap } from 'gsap'
import {
  MagnifyingGlassIcon,
  BellIcon,
  ChevronDownIcon,
  PlusIcon,
  ArrowRightOnRectangleIcon,
  Bars3Icon,
} from '@heroicons/react/24/outline'
import { useClickAway } from 'react-use'

const Header = () => {
  const [isProfileOpen, setProfileOpen] = useState(false)
  const headerRef = useRef(null)
  const profileDropdownRef = useRef(null)

  useClickAway(profileDropdownRef, () => {
    if (isProfileOpen) {
      setProfileOpen(false)
    }
  })

  useEffect(() => {
    gsap.fromTo(
      headerRef.current,
      {
        opacity: 0,
        y: -80,
      },
      {
        opacity: 1,
        y: 0,
        duration: 0.8,
        ease: 'power3.out',
        delay: 0.2,
      },
    )
  }, [])

  useEffect(() => {
    if (isProfileOpen) {
      gsap.fromTo(
        profileDropdownRef.current,
        { opacity: 0, scale: 0.95, y: -20 },
        { opacity: 1, scale: 1, y: 0, duration: 0.2, ease: 'power2.out' },
      )
    }
  }, [isProfileOpen])

  return (
    <header ref={headerRef} className="bg-surface sticky top-0 z-20 w-full opacity-0">
      <div className="flex items-center justify-between p-4 border-b border-border">
        {/* Left Side: Search Bar */}
        <div className="flex items-center space-x-4">
          <button className="md:hidden text-text-secondary hover:text-text-primary">
            <Bars3Icon className="h-6 w-6" />
          </button>
          <div className="relative hidden sm:block">
            <MagnifyingGlassIcon className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-text-secondary" />
            <input
              type="text"
              placeholder="Search by VIN, Customer, Estimate #"
              className="bg-background text-text-primary placeholder-text-secondary w-64 md:w-80 lg:w-96 pl-12 pr-4 py-2.5 rounded-lg border border-transparent focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all duration-300"
            />
          </div>
        </div>

        {/* Right Side: Actions & Profile */}
        <div className="flex items-center space-x-4 md:space-x-6">
          <NavLink
            to="/new-estimate"
            className="hidden sm:flex items-center justify-center bg-accent hover:bg-accent-dark text-background font-bold py-2 px-4 rounded-lg shadow-lg hover:shadow-xl transform hover:-translate-y-0.5 transition-all duration-300 ease-in-out"
          >
            <PlusIcon className="h-5 w-5 mr-2" />
            <span>New Estimate</span>
          </NavLink>

          <button className="relative text-text-secondary hover:text-text-primary transition-colors">
            <BellIcon className="h-6 w-6" />
            <span className="absolute -top-1 -right-1 bg-danger text-white text-[10px] rounded-full h-4 w-4 flex items-center justify-center">
              2
            </span>
          </button>

          <div className="relative" ref={profileDropdownRef}>
            <button
              onClick={() => setProfileOpen(!isProfileOpen)}
              className="flex items-center space-x-2 focus:outline-none"
            >
              <div className="h-10 w-10 bg-primary rounded-full flex items-center justify-center text-text-primary font-bold text-lg">
                AS
              </div>
              <div className="hidden md:flex flex-col items-start">
                <p className="font-semibold text-text-primary text-sm">Sergio</p>
                <p className="text-xs text-text-secondary">Advisor</p>
              </div>
              <ChevronDownIcon
                className={`h-5 w-5 text-text-secondary hidden md:block transition-transform duration-300 ${
                  isProfileOpen ? 'rotate-180' : ''
                }`}
              />
            </button>

            {isProfileOpen && (
              <div className="absolute right-0 mt-3 w-48 bg-surface border border-border rounded-lg shadow-2xl py-2">
                <div className="px-4 py-2 border-b border-border">
                  <p className="font-bold text-text-primary">Sergio</p>
                  <p className="text-sm text-text-secondary">Advisor</p>
                </div>
                <button className="w-full flex items-center px-4 py-2 text-left text-text-secondary hover:bg-primary-light hover:text-text-primary transition-colors">
                  <ArrowRightOnRectangleIcon className="h-5 w-5 mr-3" />
                  Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

export default Header
