// src/components/estimate-steps/PreviewStep.jsx

const PreviewRow = ({ label, value, isTotal = false }) => (
  <div
    className={`flex justify-between items-center py-4 ${
      isTotal ? '' : 'border-b border-border/50'
    }`}
  >
    <p className={`font-semibold ${isTotal ? 'text-xl text-text-primary' : 'text-text-secondary'}`}>
      {label}
    </p>
    <p
      className={`font-mono font-bold ${
        isTotal ? 'text-2xl text-text-primary' : 'text-lg text-text-primary'
      }`}
    >
      {value}
    </p>
  </div>
)

const PreviewStep = () => (
  <div className="space-y-8">
    <h2 className="text-2xl font-bold text-text-primary">Estimate Preview</h2>

    {/* Summary Section */}
    <div className="bg-background p-6 rounded-lg border border-border">
      <PreviewRow label="Labor" value="$144.00" />
      <PreviewRow label="Parts" value="$636.00" />
      <PreviewRow label="Tax (9.5%)" value="$74.10" />
      <div className="pt-4">
        <PreviewRow label="Total" value="$854.10" isTotal={true} />
      </div>
    </div>

    {/* Notes Section */}
    <div className="bg-background p-4 rounded-lg flex justify-between items-center">
      <p className="text-sm text-text-secondary">Notes</p>
      <p className="text-sm text-text-secondary">
        Estimate auto-generated • Sources:
        <span className="ml-2 px-2 py-1 bg-primary/50 text-text-primary text-xs rounded-md">
          ALLDATA
        </span>
        <span className="ml-2 px-2 py-1 bg-primary/50 text-text-primary text-xs rounded-md">
          PartsLink24
        </span>
      </p>
    </div>

    {/* Actions Section */}
    <div className="flex items-center space-x-4">
      <button className="bg-accent hover:bg-accent-dark text-background font-bold py-3 px-6 rounded-lg transition-colors">
        Push to Tekmetric
      </button>
      <button className="bg-surface border border-border text-text-secondary font-bold py-3 px-6 rounded-lg hover:bg-primary-light hover:text-text-primary transition-colors">
        Send Approval Link
      </button>
      <button className="bg-surface border border-border text-text-secondary font-bold py-3 px-6 rounded-lg hover:bg-primary-light hover:text-text-primary transition-colors">
        Print PDF
      </button>
    </div>
  </div>
)

export default PreviewStep
