import React, { useState, useEffect } from 'react'

const customersData = [
  {
    id: 1,
    name: 'John Carter',
    phone: '(415) 555-2121',
    email: 'john@example.com',
    vehicles: ['BMW 328i'],
    estimates: 3,
    lastVisit: '8/30/2025',
  },
  {
    id: 2,
    name: 'Emily Wong',
    phone: '(510) 555-8822',
    email: 'emily@example.com',
    vehicles: ['Audi A4', 'VW GTI'],
    estimates: 5,
    lastVisit: '7/28/2025',
  },
  {
    id: 3,
    name: 'Carlos Ruiz',
    phone: '(925) 555-7711',
    email: 'carlos@example.com',
    vehicles: ['Porsche 911'],
    estimates: 1,
    lastVisit: '9/8/2025',
  },
]

const CustomersPage = () => {
  const [selectedCustomer, setSelectedCustomer] = useState(customersData[0])

  // Icons from Lucide React as inline SVGs
  const LucidePhone = ({ className }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )

  const LucideMail = ({ className }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )

  const LucideCalendar = ({ className }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
      <line x1="16" x2="16" y1="2" y2="6" />
      <line x1="8" x2="8" y1="2" y2="6" />
      <line x1="3" x2="21" y1="10" y2="10" />
    </svg>
  )

  const LucideCar = ({ className }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9L14 6L4 6c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h2v3c0 1.1.9 2 2 2h2c.6 0 1 .4 1 1v1c0 .6-.4 1-1 1H4a2 2 0 0 1-2-2v-3c0-1.1.9-2 2-2h4v-1.5c0-.8.7-1.5 1.5-1.5h.5c.8 0 1.5.7 1.5 1.5v1.5h4v-1.5c0-.8.7-1.5 1.5-1.5h.5c.8 0 1.5.7 1.5 1.5v1.5h4v3c0 1.1-.9 2-2 2h-2" />
    </svg>
  )

  const LucideFileText = ({ className }) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" x2="8" y1="13" y2="13" />
      <line x1="16" x2="8" y1="17" y2="17" />
      <line x1="10" x2="8" y1="9" y2="9" />
    </svg>
  )

  const DetailItem = ({ icon, label, value }) => (
    <div className="flex items-center justify-between p-4 border-b border-gray-700 last:border-b-0">
      <div className="flex items-center text-gray-400 font-medium">
        {icon}
        <span className="ml-2">{label}</span>
      </div>
      <span className="text-sm font-semibold text-white">{value}</span>
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
      <div className="flex flex-col lg:flex-row gap-6 lg:h-[calc(100vh-4rem)]">
        {/* Customers Table Section */}
        <div className="flex-1 bg-[#1a202c] rounded-2xl p-6 shadow-xl overflow-hidden flex flex-col">
          <h2 className="text-2xl font-bold mb-6 text-gray-200">Customers</h2>
          <div className="flex-1 overflow-auto rounded-lg">
            <table className="w-full text-left text-sm whitespace-nowrap table-auto">
              <thead className="sticky top-0 bg-[#1a202c] text-gray-400 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Name
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold hidden lg:table-cell">
                    Phone
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold hidden md:table-cell">
                    Email
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold hidden sm:table-cell">
                    Vehicles
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Estimates
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold hidden md:table-cell">
                    Last Visit
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {customersData.map((customer) => (
                  <tr
                    key={customer.id}
                    className={`cursor-pointer transition-all duration-200 hover:bg-[#2a4376] ${
                      selectedCustomer.id === customer.id ? 'bg-[#2a4376]' : 'bg-transparent'
                    }`}
                    onClick={() => setSelectedCustomer(customer)}
                  >
                    <td className="px-6 py-4 font-medium text-white">{customer.name}</td>
                    <td className="px-6 py-4 text-gray-300 hidden lg:table-cell">
                      {customer.phone}
                    </td>
                    <td className="px-6 py-4 text-gray-300 hidden md:table-cell">
                      {customer.email}
                    </td>
                    <td className="px-6 py-4 text-gray-300 hidden sm:table-cell">
                      {customer.vehicles.join(', ')}
                    </td>
                    <td className="px-6 py-4 text-gray-300">{customer.estimates}</td>
                    <td className="px-6 py-4 text-gray-300 hidden md:table-cell">
                      {customer.lastVisit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Details Section */}
        <div className="lg:w-1/3 bg-[#1a202c] rounded-2xl p-6 shadow-xl overflow-hidden flex flex-col">
          <h2 className="text-2xl font-bold mb-6 text-gray-200">Details</h2>
          <div className="flex-1 space-y-4">
            {selectedCustomer && (
              <>
                <DetailItem
                  icon={<LucideMail className="w-5 h-5 text-gray-400" />}
                  label="Email"
                  value={selectedCustomer.email}
                />
                <DetailItem
                  icon={<LucidePhone className="w-5 h-5 text-gray-400" />}
                  label="Contact"
                  value={selectedCustomer.phone}
                />
                <DetailItem
                  icon={<LucideCar className="w-5 h-5 text-gray-400" />}
                  label="Vehicles"
                  value={selectedCustomer.vehicles.join(', ')}
                />
                <DetailItem
                  icon={<LucideFileText className="w-5 h-5 text-gray-400" />}
                  label="Estimates"
                  value={selectedCustomer.estimates}
                />
                <DetailItem
                  icon={<LucideCalendar className="w-5 h-5 text-gray-400" />}
                  label="Last Visit"
                  value={selectedCustomer.lastVisit}
                />
              </>
            )}
            {!selectedCustomer && (
              <div className="text-center text-gray-400 mt-10">
                Select a customer to see details.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default CustomersPage
