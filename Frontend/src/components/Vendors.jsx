import React, { useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend } from 'recharts'

const data = [
  { name: 'Worldpac', value: 400, color: '#00BFFF' },
  { name: 'SSF', value: 300, color: '#B2E742' },
]

const VendorsPage = () => {
  const [primaryBrands, setPrimaryBrands] = useState('')
  const [backupBrands, setBackupBrands] = useState('')

  const handleSave = () => {
    // Here you would save the brand preferences, for example, to a database
    // For this example, we'll just log the data to the console
    console.log('Primary Brands:', primaryBrands)
    console.log('Backup Options:', backupBrands)
    alert('Preferences saved successfully!')
  }

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-[#0d1117] text-white font-inter">
      <style>{`
        /* Custom Scrollbar Styles for the entire app */
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
      <div className="flex flex-col gap-6">
        {/* Metrics Cards Section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Usage % Card */}
          <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl flex flex-col items-center">
            <h3 className="text-lg font-semibold text-gray-400 mb-4">Usage %</h3>
            <div className="flex-grow flex items-center justify-center w-full">
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={data}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    fill="#8884d8"
                    paddingAngle={5}
                    dataKey="value"
                    isAnimationActive={true}
                  >
                    {data.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Legend
                    verticalAlign="bottom"
                    height={36}
                    content={(props) => (
                      <div className="flex justify-center mt-4 text-xs font-semibold">
                        {props.payload.map((entry, index) => (
                          <div
                            key={`legend-${index}`}
                            className="flex items-center mx-2 text-gray-400"
                          >
                            <span
                              className="inline-block w-2.5 h-2.5 rounded-full mr-1.5"
                              style={{ backgroundColor: entry.color }}
                            ></span>
                            {entry.value}
                          </div>
                        ))}
                      </div>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Avg. Delivery Distance Card */}
          <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl flex flex-col justify-between">
            <h3 className="text-lg font-semibold text-gray-400 mb-4">Avg. Delivery Distance</h3>
            <div className="flex-grow flex items-center justify-center">
              <span className="text-5xl font-bold text-white">27.2 km</span>
            </div>
          </div>

          {/* Avg. Part Price Card */}
          <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl flex flex-col justify-between">
            <h3 className="text-lg font-semibold text-gray-400 mb-4">Avg. Part Price</h3>
            <div className="flex-grow flex items-center justify-center">
              <span className="text-5xl font-bold text-white">$215.24</span>
            </div>
          </div>
        </div>

        {/* Preferences Section */}
        <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl">
          <h2 className="text-2xl font-bold mb-6 text-gray-200">Preferences</h2>
          <div className="flex flex-col md:flex-row items-end gap-4">
            <div className="flex-1 w-full">
              <label
                htmlFor="primary-brands"
                className="block text-sm font-medium text-gray-400 mb-2"
              >
                Primary Brands
              </label>
              <input
                type="text"
                id="primary-brands"
                className="w-full bg-[#30363d] text-white border-none rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-[#2a4376]"
                placeholder="e.g., Bosch, ATE, Mahle"
                value={primaryBrands}
                onChange={(e) => setPrimaryBrands(e.target.value)}
              />
            </div>
            <div className="flex-1 w-full">
              <label
                htmlFor="backup-options"
                className="block text-sm font-medium text-gray-400 mb-2"
              >
                Backup Options
              </label>
              <input
                type="text"
                id="backup-options"
                className="w-full bg-[#30363d] text-white border-none rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-[#2a4376]"
                placeholder="e.g., Mann, TRW"
                value={backupBrands}
                onChange={(e) => setBackupBrands(e.target.value)}
              />
            </div>
            <button
              onClick={handleSave}
              className="w-full md:w-auto px-6 py-3 bg-[#34d399] text-gray-900 font-bold rounded-lg transition-colors duration-200 hover:bg-[#10b981] shadow-lg"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default VendorsPage
