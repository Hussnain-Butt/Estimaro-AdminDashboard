import React, { useState } from 'react'
import { Sliders, Mail, Smartphone, ChevronRight } from 'lucide-react'

const SettingsPage = () => {
  const [laborRate, setLaborRate] = useState(160)
  const [partsMarkup, setPartsMarkup] = useState(20)
  const [tax, setTax] = useState(9.5)
  const [brandWeight, setBrandWeight] = useState(50)
  const [priceWeight, setPriceWeight] = useState(50)
  const [distanceWeight, setDistanceWeight] = useState(50)
  const [newAdvisor, setNewAdvisor] = useState('')
  const [advisors, setAdvisors] = useState(['Sergio', 'Alex', 'Jordan'])
  const [emailTemplate, setEmailTemplate] = useState('Dear {{customer}}, your estimate is ready...')
  const [smsTemplate, setSmsTemplate] = useState('Hi {{customer}}, view your estimate: {{link}}')

  const addAdvisor = () => {
    if (newAdvisor.trim() !== '' && !advisors.includes(newAdvisor.trim())) {
      setAdvisors([...advisors, newAdvisor.trim()])
      setNewAdvisor('')
    }
  }

  const removeAdvisor = (name) => {
    setAdvisors(advisors.filter((advisor) => advisor !== name))
  }

  const Section = ({ title, children }) => (
    <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl mb-6">
      <h2 className="text-2xl font-bold text-gray-200 mb-4 flex items-center">{title}</h2>
      <div className="space-y-4">{children}</div>
    </div>
  )

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-[#0d1117] text-white font-inter">
      <style>{`
        /* Custom Scrollbar Styles */
        ::-webkit-scrollbar {
          width: 10px;
        }
        ::-webkit-scrollbar-track {
          background: #0d1117;
        }
        ::-webkit-scrollbar-thumb {
          background-color: #30363d;
          border-radius: 20px;
          border: 2px solid #0d1117;
        }
        ::-webkit-scrollbar-thumb:hover {
          background-color: #4a6ead;
        }
      `}</style>

      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <h1 className="text-3xl font-extrabold text-white mb-6">Settings</h1>

        {/* Shop Settings */}
        <Section title="Shop Settings (German Sport)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-end">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Labor Rate ($/hr)
              </label>
              <input
                type="number"
                value={laborRate}
                onChange={(e) => setLaborRate(e.target.value)}
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Parts Markup (%)
              </label>
              <input
                type="number"
                value={partsMarkup}
                onChange={(e) => setPartsMarkup(e.target.value)}
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Tax %</label>
              <input
                type="number"
                value={tax}
                onChange={(e) => setTax(e.target.value)}
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <button className="bg-gradient-to-br from-[#34d399] to-[#10b981] text-gray-900 font-bold py-3 px-6 rounded-lg shadow-lg hover:from-[#10b981] hover:to-[#34d399] transition-all transform hover:scale-105">
              Save
            </button>
          </div>
        </Section>

        {/* Scoring Weights */}
        <Section title="Scoring Weights">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
            <div className="flex flex-col items-start">
              <label className="text-sm font-medium text-gray-400 mb-3">Brand</label>
              <input
                type="range"
                min="0"
                max="100"
                value={brandWeight}
                onChange={(e) => setBrandWeight(e.target.value)}
                className="w-full h-2 bg-[#30363d] rounded-lg appearance-none cursor-pointer"
              />
            </div>
            <div className="flex flex-col items-start">
              <label className="text-sm font-medium text-gray-400 mb-3">Price</label>
              <input
                type="range"
                min="0"
                max="100"
                value={priceWeight}
                onChange={(e) => setPriceWeight(e.target.value)}
                className="w-full h-2 bg-[#30363d] rounded-lg appearance-none cursor-pointer"
              />
            </div>
            <div className="flex flex-col items-start">
              <label className="text-sm font-medium text-gray-400 mb-3">Distance</label>
              <input
                type="range"
                min="0"
                max="100"
                value={distanceWeight}
                onChange={(e) => setDistanceWeight(e.target.value)}
                className="w-full h-2 bg-[#30363d] rounded-lg appearance-none cursor-pointer"
              />
            </div>
          </div>
        </Section>

        {/* Integrations */}
        <Section title="Integrations">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Tekmetric API Key
              </label>
              <input
                type="password"
                defaultValue="••••••••"
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                ALLDATA Credentials
              </label>
              <input
                type="text"
                placeholder="user,pass"
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                PartsLink24 Token
              </label>
              <input
                type="password"
                defaultValue="••••••••"
                className="w-full bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
            </div>
          </div>
        </Section>

        {/* User Management */}
        <Section title="User Management">
          <div className="flex flex-col sm:flex-row items-start sm:items-center space-y-4 sm:space-y-0 sm:space-x-4">
            <div className="flex-1 w-full">
              <label className="block text-sm font-medium text-gray-400 mb-1">Add Advisor</label>
              <div className="flex">
                <input
                  type="text"
                  placeholder="Name"
                  value={newAdvisor}
                  onChange={(e) => setNewAdvisor(e.target.value)}
                  className="flex-1 bg-[#30363d] text-white rounded-l-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
                />
                <button
                  onClick={addAdvisor}
                  className="bg-gradient-to-br from-[#34d399] to-[#10b981] text-gray-900 font-bold py-3 px-6 rounded-r-lg shadow-lg hover:from-[#10b981] hover:to-[#34d399] transition-all"
                >
                  Add
                </button>
              </div>
            </div>
            <div className="flex-1 w-full flex flex-wrap items-center space-x-2 space-y-2 pt-6 sm:pt-0">
              {advisors.map((advisor, index) => (
                <span
                  key={index}
                  className="bg-[#4a6ead] text-white text-sm font-medium px-4 py-2 rounded-full cursor-pointer transition-all hover:bg-[#2a4376]"
                  onClick={() => removeAdvisor(advisor)}
                >
                  {advisor}
                </span>
              ))}
            </div>
          </div>
        </Section>

        {/* Notifications */}
        <Section title="Notifications">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1 flex items-center">
                <Mail size={16} className="mr-2" /> Email Template
              </label>
              <textarea
                value={emailTemplate}
                onChange={(e) => setEmailTemplate(e.target.value)}
                className="w-full h-48 bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all resize-y"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1 flex items-center">
                <Smartphone size={16} className="mr-2" /> SMS Template
              </label>
              <textarea
                value={smsTemplate}
                onChange={(e) => setSmsTemplate(e.target.value)}
                className="w-full h-48 bg-[#30363d] text-white rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all resize-y"
              />
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}

export default SettingsPage
