// src/App.jsx

import React, { useState, useEffect } from 'react'
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './components/Dashboard'
import NewEstimate from './components/NewEstimate'
import Estimates from './components/Estimates'
import Customers from './components/Customers'
import Vendors from './components/Vendors'
import Reports from './components/Reports'
import Settings from './components/Settings'
import CustomerApproval from './components/CustomerApproval'
import Login from './components/Login'
import { ToastProvider } from './components/ui/Toast'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(localStorage.getItem('estimaro_auth') === 'true')

  const handleLogin = () => {
    localStorage.setItem('estimaro_auth', 'true')
    setIsAuthenticated(true)
  }

  // Optional: Listen for storage events or simple effect if needed, but direct state setting is enough.

  return (
    <ToastProvider>
      <Router>
        <Routes>
          {/* Public Route - Login */}
          <Route
            path="/login"
            element={!isAuthenticated ? <Login onLogin={handleLogin} /> : <Navigate to="/" replace />}
          />

          {/* Public Route - Customer Approval (No Auth Required) */}
          <Route path="/approve/:token" element={<CustomerApproval />} />

          {/* Protected Dashboard Routes */}
          <Route
            path="*"
            element={
              isAuthenticated ? (
                <div className="flex h-screen bg-background text-text-primary overflow-hidden">
                  <Sidebar />
                  <div className="flex-1 flex flex-col min-w-0">
                    <Header />
                    <main className="flex-1 overflow-y-auto p-6">
                      <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/new-estimate" element={<NewEstimate />} />
                        <Route path="/estimates" element={<Estimates />} />
                        <Route path="/customers" element={<Customers />} />
                        <Route path="/vendors" element={<Vendors />} />
                        <Route path="/reports" element={<Reports />} />
                        <Route path="/settings" element={<Settings />} />
                      </Routes>
                    </main>
                  </div>
                </div>
              ) : (
                <Navigate to="/login" replace />
              )
            }
          />
        </Routes>
      </Router>
    </ToastProvider>
  )
}

export default App
