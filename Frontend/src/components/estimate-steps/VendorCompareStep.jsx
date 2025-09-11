// src/components/estimate-steps/VendorCompareStep.jsx

const VendorCompareStep = () => (
  <div className="space-y-6">
    <h2 className="text-2xl font-bold text-text-primary">Vendor Compare (Worldpac / SSF)</h2>
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-border">
            <th className="p-3 text-sm font-semibold text-text-secondary">Brand</th>
            <th className="p-3 text-sm font-semibold text-text-secondary">Price</th>
            <th className="p-3 text-sm font-semibold text-text-secondary">Stock</th>
            <th className="p-3 text-sm font-semibold text-text-secondary">Distance</th>
            <th className="p-3 text-sm font-semibold text-text-secondary">Priority</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-border/50 hover:bg-primary/20 transition-colors">
            <td className="p-4 text-text-primary font-semibold flex items-center space-x-3">
              <span className="h-4 w-4 rounded-full bg-blue-500"></span>
              <span>Brembo</span>
            </td>
            <td className="p-4 text-text-primary font-mono">$210.00</td>
            <td className="p-4 text-text-primary">6</td>
            <td className="p-4 text-text-secondary">12 km</td>
            <td className="p-4 text-success font-semibold">Primary</td>
          </tr>
          <tr className="hover:bg-primary/20 transition-colors">
            <td className="p-4 text-text-primary font-semibold flex items-center space-x-3">
              <span className="h-4 w-4 rounded-full bg-green-500"></span>
              <span>ATE</span>
            </td>
            <td className="p-4 text-text-primary font-mono">$198.00</td>
            <td className="p-4 text-text-primary">3</td>
            <td className="p-4 text-text-secondary">18 km</td>
            <td className="p-4 text-warning">Backup</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div className="bg-background p-4 rounded-lg text-text-secondary text-sm">
      <p>
        <span className="font-bold text-text-primary">Summary:</span> Brand 40 • Price 40 • Distance
        20 → <span className="text-success font-semibold">Primary: Brembo</span>
      </p>
    </div>
  </div>
)

export default VendorCompareStep
