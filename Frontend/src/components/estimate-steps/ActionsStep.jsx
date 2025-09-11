// src/components/estimate-steps/ActionsStep.jsx
import { ExclamationCircleIcon } from '@heroicons/react/24/outline'

const ValidationError = ({ text }) => (
  <div className="bg-danger/10 p-4 rounded-lg flex items-center border border-danger/20">
    <ExclamationCircleIcon className="h-6 w-6 text-danger mr-3" />
    <p className="font-semibold text-danger">{text}</p>
  </div>
)

const ActionsStep = () => (
  <div className="space-y-6 max-w-2xl mx-auto text-center">
    <h2 className="text-2xl font-bold text-text-primary">Actions & Validation</h2>
    <p className="text-text-secondary">
      Please resolve the following issues before finalizing the estimate.
    </p>
    <div className="space-y-4 text-left">
      <ValidationError text="Missing VIN" />
      <ValidationError text="Missing Service Request" />
      <ValidationError text="Missing Customer" />
    </div>
  </div>
)

export default ActionsStep
