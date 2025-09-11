// src/components/NewEstimate.jsx

import React, { useState, useRef, useEffect } from 'react'
import { gsap } from 'gsap'
import { ExclamationCircleIcon } from '@heroicons/react/24/outline'

// ===================================================================================
//  STEP COMPONENTS (Defined within the same file for simplicity)
// ===================================================================================

const IntakeStep = () => {
  const InputField = ({ label, placeholder }) => (
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-2">{label}</label>
      <input
        type="text"
        placeholder={placeholder}
        className="bg-background text-text-primary placeholder-text-secondary/50 w-full px-4 py-3 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent transition-all duration-300"
      />
    </div>
  )

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-text-primary">Intake Information</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <InputField label="VIN" placeholder="Enter or scan VIN" />
        <InputField label="Service Request" placeholder="e.g., Brake pads, Oil change" />
        <InputField label="Customer" placeholder="Start typing name..." />
        <InputField label="Odometer (km)" placeholder="Optional" />
      </div>
    </div>
  )
}

const LaborStep = () => {
  const LaborItem = ({ title, source, hours }) => (
    <div className="bg-background p-4 rounded-lg flex justify-between items-center border border-border">
      <div>
        <p className="font-semibold text-text-primary">{title}</p>
        <p className="text-xs text-text-secondary">Source: {source}</p>
      </div>
      <div className="flex items-center space-x-2">
        <input
          type="number"
          defaultValue={hours}
          className="w-20 bg-surface text-center font-semibold p-2 rounded-md border border-border focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <span className="text-text-secondary">h</span>
      </div>
    </div>
  )

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-text-primary">Labor (ALLDATA)</h2>
      <div className="space-y-4">
        <LaborItem title="Oil & filter change" source="ALLDATA" hours="0.5" />
        <LaborItem title="Multi-point inspection" source="ALLDATA" hours="0.4" />
      </div>
    </div>
  )
}

const PartsStep = () => {
  const PartItem = ({ name, number, source }) => (
    <div className="bg-background p-4 rounded-lg border border-border">
      <p className="font-semibold text-text-primary">{name}</p>
      <p className="text-xs text-text-secondary mt-1">
        {number} • Source: {source}
      </p>
    </div>
  )

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-text-primary">Parts (PartsLink24)</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PartItem name="Brembo Pad Set" number="3411-677-3456" source="PartsLink24" />
        <PartItem name="Anti-squeal paste" number="" source="PartsLink24" />
        <PartItem name="ATE Rotor (pair)" number="3411-091-2345" source="PartsLink24" />
        <PartItem name="Gasket" number="" source="PartsLink24" />
      </div>
    </div>
  )
}

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

const PreviewStep = () => {
  const PreviewRow = ({ label, value, isTotal = false }) => (
    <div
      className={`flex justify-between items-center py-4 ${
        isTotal ? '' : 'border-b border-border/50'
      }`}
    >
      <p
        className={`font-semibold ${isTotal ? 'text-xl text-text-primary' : 'text-text-secondary'}`}
      >
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

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-text-primary">Estimate Preview</h2>
      <div className="bg-background p-6 rounded-lg border border-border">
        <PreviewRow label="Labor" value="$144.00" />
        <PreviewRow label="Parts" value="$636.00" />
        <PreviewRow label="Tax (9.5%)" value="$74.10" />
        <div className="pt-4">
          <PreviewRow label="Total" value="$854.10" isTotal={true} />
        </div>
      </div>
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
}

const ActionsStep = () => {
  const ValidationError = ({ text }) => (
    <div className="bg-danger/10 p-4 rounded-lg flex items-center border border-danger/20">
      <ExclamationCircleIcon className="h-6 w-6 text-danger mr-3" />
      <p className="font-semibold text-danger">{text}</p>
    </div>
  )

  return (
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
}

// ===================================================================================
//  MAIN NEW ESTIMATE COMPONENT
// ===================================================================================

const steps = ['Intake', 'Labor', 'Parts', 'Vendor Compare', 'Preview', 'Actions']

const NewEstimate = () => {
  const [currentStep, setCurrentStep] = useState(0)
  const contentRef = useRef(null)

  const animateStep = () => {
    // Only animate the entrance of the new content
    gsap.fromTo(
      contentRef.current,
      { opacity: 0, x: 30 },
      { opacity: 1, x: 0, duration: 0.5, ease: 'power3.out' },
    )
  }

  useEffect(() => {
    animateStep()
  }, [currentStep])

  const handleNext = () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep((prev) => prev + 1)
    }
  }

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1)
    }
  }

  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return <IntakeStep />
      case 1:
        return <LaborStep />
      case 2:
        return <PartsStep />
      case 3:
        return <VendorCompareStep />
      case 4:
        return <PreviewStep />
      case 5:
        return <ActionsStep />
      default:
        return <IntakeStep />
    }
  }

  return (
    <div className="p-4 md:p-8 min-h-full flex flex-col">
      {/* Top Section: Stepper and Save Draft button */}
      <div className="flex justify-between items-center mb-8">
        <div className="flex items-center space-x-2 md:space-x-4">
          {steps.map((step, index) => (
            <div key={index} className="flex items-center">
              <div
                className={`flex items-center justify-center w-8 h-8 rounded-full font-bold transition-all duration-300 ${
                  currentStep === index
                    ? 'bg-accent text-background scale-110 shadow-lg shadow-accent/30'
                    : currentStep > index
                    ? 'bg-primary text-text-primary'
                    : 'bg-surface border-2 border-border text-text-secondary'
                }`}
              >
                {index + 1}
              </div>
              <span
                className={`ml-3 hidden md:block font-semibold ${
                  currentStep === index ? 'text-text-primary' : 'text-text-secondary'
                }`}
              >
                {step}
              </span>
            </div>
          ))}
        </div>
        <button className="bg-surface border border-border text-text-secondary px-4 py-2 rounded-lg hover:bg-primary-light hover:text-text-primary transition-colors">
          Save Draft
        </button>
      </div>

      {/* Main Content Area for Steps */}
      <div className="flex-grow bg-surface border border-border rounded-xl p-6 md:p-8">
        <div ref={contentRef}>{renderStepContent()}</div>
      </div>

      {/* Bottom Navigation */}
      <div className="flex justify-between items-center mt-8">
        <button
          onClick={handleBack}
          className={`px-6 py-3 rounded-lg font-bold transition-all duration-300 bg-surface border border-border text-text-secondary hover:bg-primary-light hover:text-text-primary ${
            currentStep === 0 ? 'opacity-50 cursor-not-allowed' : ''
          }`}
          disabled={currentStep === 0}
        >
          Back
        </button>
        <button
          onClick={handleNext}
          className={`px-8 py-3 rounded-lg font-bold text-background transition-all duration-300 transform hover:-translate-y-1 hover:shadow-xl ${
            currentStep === steps.length - 1
              ? 'bg-success hover:bg-success/80 shadow-lg shadow-success/30'
              : 'bg-accent hover:bg-accent-dark shadow-lg shadow-accent/30'
          }`}
        >
          {currentStep === steps.length - 1 ? 'Finish Estimate' : 'Next'}
        </button>
      </div>
    </div>
  )
}

export default NewEstimate
