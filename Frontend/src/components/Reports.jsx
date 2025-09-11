import React from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'

// Data for all six charts
const timeSavedData = [
  { name: 'Mon', Minutes: 30 },
  { name: 'Tue', Minutes: 42 },
  { name: 'Wed', Minutes: 25 },
  { name: 'Thu', Minutes: 55 },
  { name: 'Fri', Minutes: 40 },
  { name: 'Sat', Minutes: 70 },
  { name: 'Sun', Minutes: 65 },
]

const approvalRateData = [
  { name: 'Mon', 'Approval %': 54 },
  { name: 'Tue', 'Approval %': 62 },
  { name: 'Wed', 'Approval %': 66 },
  { name: 'Thu', 'Approval %': 62 },
  { name: 'Fri', 'Approval %': 69 },
  { name: 'Sat', 'Approval %': 71 },
  { name: 'Sun', 'Approval %': 72 },
]

const averageEstimateData = [
  { name: 'Mon', USD: 700 },
  { name: 'Tue', USD: 720 },
  { name: 'Wed', USD: 705 },
  { name: 'Thu', USD: 760 },
  { name: 'Fri', USD: 800 },
  { name: 'Sat', USD: 820 },
  { name: 'Sun', USD: 790 },
]

const vendorUsageData = [
  { name: 'Mon', 'Worldpac %': 60 },
  { name: 'Tue', 'Worldpac %': 64 },
  { name: 'Wed', 'Worldpac %': 62 },
  { name: 'Thu', 'Worldpac %': 65 },
  { name: 'Fri', 'Worldpac %': 62 },
  { name: 'Sat', 'Worldpac %': 63 },
  { name: 'Sun', 'Worldpac %': 61 },
]

const costSavingsData = [
  { name: 'Mon', Savings: 120 },
  { name: 'Tue', Savings: 150 },
  { name: 'Wed', Savings: 130 },
  { name: 'Thu', Savings: 170 },
  { name: 'Fri', Savings: 160 },
  { name: 'Sat', Savings: 200 },
  { name: 'Sun', Savings: 190 },
]

const customerSatisfactionData = [
  { name: 'Mon', 'Satisfaction %': 85 },
  { name: 'Tue', 'Satisfaction %': 88 },
  { name: 'Wed', 'Satisfaction %': 86 },
  { name: 'Thu', 'Satisfaction %': 90 },
  { name: 'Fri', 'Satisfaction %': 92 },
  { name: 'Sat', 'Satisfaction %': 95 },
  { name: 'Sun', 'Satisfaction %': 93 },
]

const ReportsPage = () => {
  const Card = ({ title, children }) => (
    <div className="bg-[#1a202c] rounded-2xl p-6 shadow-xl flex flex-col">
      <h3 className="text-xl font-bold mb-4 text-gray-200">{title}</h3>
      <div className="flex-1 w-full h-64">{children}</div>
    </div>
  )

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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Time Saved vs Manual Chart */}
        <Card title="Time Saved vs Manual">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={timeSavedData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="Minutes"
                stroke="#B2E742"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Approval Rate Trend Chart */}
        <Card title="Approval Rate Trend">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={approvalRateData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="Approval %"
                stroke="#00BFFF"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Average Estimate Value Chart */}
        <Card title="Average Estimate Value">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={averageEstimateData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="USD"
                stroke="#FFCC00"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Vendor Usage Chart */}
        <Card title="Vendor Usage">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={vendorUsageData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="Worldpac %"
                stroke="#ef4444"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Cost Savings Trend Chart */}
        <Card title="Cost Savings Trend">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={costSavingsData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="Savings"
                stroke="#34d399"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Customer Satisfaction Chart */}
        <Card title="Customer Satisfaction">
          <ResponsiveContainer width="99%" height={256}>
            <LineChart data={customerSatisfactionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
              <XAxis dataKey="name" stroke="#8b949e" />
              <YAxis stroke="#8b949e" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a202c',
                  border: '1px solid #30363d',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: '#f0f6fc' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="Satisfaction %"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  )
}

export default ReportsPage
