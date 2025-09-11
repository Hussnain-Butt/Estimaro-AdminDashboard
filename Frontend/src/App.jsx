// src/App.jsx

import React from 'react'
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './components/Dashboard'
import NewEstimate from './components/NewEstimate'
import Estimates from './components/Estimates'
import Customers from './components/Customers'
import Vendors from './components/Vendors'
import Reports from './components/Reports'
import Settings from './components/Settings'

function App() {
  return (
    <Router>
      {/* Old: bg-gray-900, New: bg-background */}
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
    </Router>
  )
}

export default App
