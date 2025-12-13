// src/components/estimate-steps/VendorCompareStep.jsx
// Dynamic Vendor Comparison with Scoring Display

const VendorCompareStep = ({ vendorData }) => {
  // If no vendor data yet, show placeholder
  if (!vendorData || !vendorData.parts || vendorData.parts.length === 0) {
    return (
      <div className="space-y-6">
        <h2 className="text-2xl font-bold text-text-primary">Vendor Compare (Worldpac / SSF)</h2>
        <div className="bg-background p-8 rounded-lg border border-border text-center">
          <p className="text-text-secondary mb-4">Vendor comparison data will appear here</p>
          <p className="text-sm text-text-secondary">
            Use Auto-Generate to compare prices across vendors
          </p>
        </div>
      </div>
    )
  }

  const weights = vendorData.weights || { brand: 40, price: 35, distance: 25 }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-text-primary">Vendor Compare (Worldpac / SSF)</h2>
        <div className="text-sm text-text-secondary">
          Weights: Brand {weights.brand}% • Price {weights.price}% • Distance {weights.distance}%
        </div>
      </div>
      
      {vendorData.parts.map((part, partIndex) => (
        <div key={partIndex} className="bg-background rounded-lg border border-border overflow-hidden">
          <div className="bg-primary/20 px-4 py-2 border-b border-border">
            <p className="font-semibold text-text-primary">{part.description || part.part_number}</p>
            <p className="text-xs text-text-secondary">Part #: {part.part_number}</p>
          </div>
          
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border bg-surface/50">
                  <th className="p-3 text-sm font-semibold text-text-secondary">Vendor</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Brand</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Price</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Stock</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Distance</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Score</th>
                  <th className="p-3 text-sm font-semibold text-text-secondary">Selection</th>
                </tr>
              </thead>
              <tbody>
                {part.offers && part.offers.map((offer, offerIndex) => (
                  <tr 
                    key={offerIndex} 
                    className={`border-b border-border/50 hover:bg-primary/10 transition-colors ${
                      offer.selection === 'Primary' ? 'bg-success/10' : 
                      offer.selection === 'Backup' ? 'bg-warning/10' : ''
                    }`}
                  >
                    <td className="p-3 text-text-primary font-semibold">
                      <div className="flex items-center space-x-2">
                        <span className={`h-3 w-3 rounded-full ${
                          offer.vendor_name === 'Worldpac' ? 'bg-blue-500' : 'bg-green-500'
                        }`}></span>
                        <span>{offer.vendor_name}</span>
                      </div>
                    </td>
                    <td className="p-3">
                      <div>
                        <p className="text-text-primary font-medium">{offer.brand}</p>
                        <p className="text-xs text-text-secondary">{offer.brand_tier}</p>
                      </div>
                    </td>
                    <td className="p-3 text-text-primary font-mono">${parseFloat(offer.price).toFixed(2)}</td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded text-xs ${
                        offer.stock_status === 'In Stock' || offer.stock_status === 'Available' 
                          ? 'bg-success/20 text-success' 
                          : 'bg-warning/20 text-warning'
                      }`}>
                        {offer.stock_status} ({offer.stock_quantity})
                      </span>
                    </td>
                    <td className="p-3 text-text-secondary">{offer.distance_miles} mi</td>
                    <td className="p-3">
                      <div className="flex items-center space-x-2">
                        <div className="w-16 h-2 bg-background rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-accent rounded-full" 
                            style={{ width: `${offer.scores?.composite || 0}%` }}
                          ></div>
                        </div>
                        <span className="text-text-primary font-bold">{offer.scores?.composite || 0}</span>
                      </div>
                    </td>
                    <td className="p-3">
                      {offer.selection === 'Primary' && (
                        <span className="px-3 py-1 bg-success text-background rounded-full text-xs font-bold">
                          ★ Primary
                        </span>
                      )}
                      {offer.selection === 'Backup' && (
                        <span className="px-3 py-1 bg-warning text-background rounded-full text-xs font-bold">
                          Backup
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* Part Summary */}
          {part.primary && (
            <div className="bg-surface/50 px-4 py-3 border-t border-border flex justify-between items-center">
              <p className="text-sm text-text-secondary">
                <span className="font-bold text-text-primary">Recommended:</span>{' '}
                {part.primary.brand} from {part.primary.vendor}
              </p>
              <p className="text-sm font-bold text-accent">${parseFloat(part.primary.price).toFixed(2)}</p>
            </div>
          )}
        </div>
      ))}
      
      {/* Summary */}
      <div className="bg-background p-4 rounded-lg border border-border">
        <div className="flex justify-between items-center">
          <p className="text-sm text-text-secondary">
            <span className="font-bold text-text-primary">Vendors Queried:</span>{' '}
            {vendorData.summary?.vendors_queried?.join(', ') || 'Worldpac, SSF'}
          </p>
          <p className="text-xs text-text-secondary">
            {vendorData.summary?.note || 'Live vendor integration'}
          </p>
        </div>
      </div>
    </div>
  )
}

export default VendorCompareStep
