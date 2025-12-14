import React, { useState, useRef, useEffect } from 'react'
import { gsap } from 'gsap'
import { ExclamationCircleIcon, TrashIcon, PlusIcon, SparklesIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline'
import { autoGenerateEstimate, pushToTekmetric, generateApprovalLink, createDraftEstimate } from '../services/api'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import VendorCompareStep from './estimate-steps/VendorCompareStep'

// ===================================================================================
//  STEP COMPONENTS
// ===================================================================================

const IntakeStep = ({ data, updateData }) => {
  const InputField = ({ label, placeholder, value, fieldKey, type = "text", required = false }) => (
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-2">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => updateData(fieldKey, e.target.value)}
        className="bg-background text-text-primary placeholder-text-secondary/50 w-full px-4 py-3 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent transition-all duration-300"
      />
    </div>
  )

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-text-primary">Intake Information</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <InputField
          label="VIN"
          placeholder="Enter 17-character VIN"
          value={data.vin}
          fieldKey="vin"
          required
        />
        <InputField
          label="Service Request"
          placeholder="e.g., Brake pads, Oil change"
          value={data.serviceRequest}
          fieldKey="serviceRequest"
          required
        />
        <InputField
          label="Customer Name"
          placeholder="Full name"
          value={data.customerName}
          fieldKey="customerName"
          required
        />
        <InputField
          label="Customer Email"
          placeholder="email@example.com"
          value={data.customerEmail}
          fieldKey="customerEmail"
          type="email"
        />
        <InputField
          label="Customer Phone"
          placeholder="+1-555-123-4567"
          value={data.customerPhone}
          fieldKey="customerPhone"
          required
        />
        <InputField
          label="Odometer (km)"
          placeholder="Optional"
          value={data.odometer}
          fieldKey="odometer"
          type="number"
        />
      </div>
    </div>
  )
}

const LaborStep = ({ data }) => {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-text-primary">Labor (ALLDATA)</h2>
        <span className="text-sm text-text-secondary">Rate: ${data.laborRate}/hr</span>
      </div>

      {data.laborItems.length === 0 ? (
        <div className="bg-background p-8 rounded-lg border border-border text-center">
          <p className="text-text-secondary">No labor items yet. Use Auto-Generate to populate.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {data.laborItems.map((item, index) => (
            <div
              key={index}
              className="bg-background p-4 rounded-lg flex justify-between items-center border border-border"
            >
              <div>
                <p className="font-semibold text-text-primary">{item.description}</p>
                <p className="text-xs text-text-secondary">Source: {item.source || 'ALLDATA'}</p>
              </div>
              <div className="flex items-center space-x-2">
                <span className="text-text-primary font-semibold">{item.hours}h</span>
                <span className="text-text-secondary">×</span>
                <span className="text-text-primary font-semibold">${item.rate}/hr</span>
                <span className="text-text-secondary">=</span>
                <span className="text-accent font-bold">${item.total}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="bg-surface/50 p-4 rounded-lg border border-border/50 text-right">
        <p className="text-text-secondary">
          Total Labor Hours:{' '}
          <span className="font-bold text-text-primary">
            {data.laborItems.reduce((acc, item) => acc + parseFloat(item.hours || 0), 0).toFixed(1)}h
          </span>
        </p>
      </div>
    </div>
  )
}

const PartsStep = ({ data }) => {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-text-primary">Parts (PartsLink24)</h2>

      {data.partsItems.length === 0 ? (
        <div className="bg-background p-8 rounded-lg border border-border text-center">
          <p className="text-text-secondary">No parts yet. Use Auto-Generate to populate.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.partsItems.map((part, index) => (
            <div
              key={index}
              className="bg-background p-4 rounded-lg border border-border"
            >
              <div>
                <p className="font-semibold text-text-primary">{part.description}</p>
                <p className="text-xs text-text-secondary mt-1">
                  {part.partNumber || 'N/A'} • Vendor: {part.vendor || 'Unknown'}
                </p>
                {part.isOEM && (
                  <span className="inline-block mt-1 mr-2 px-2 py-0.5 bg-accent/20 text-accent text-xs rounded">
                    OEM
                  </span>
                )}
                {part.reasonBadge && (
                  <span className="inline-block mt-1 px-2 py-0.5 bg-info/20 text-info text-xs rounded border border-info/30 flex items-center gap-1 w-fit">
                    <SparklesIcon className="h-3 w-3" />
                    {part.reasonBadge}
                  </span>
                )}
                <div className="mt-2 flex items-center gap-2 text-sm">
                  <span className="text-text-secondary">Qty: {part.quantity}</span>
                  <span className="text-text-secondary">×</span>
                  <span className="text-text-secondary">${part.cost}</span>
                  <span className="text-text-secondary">+{part.markup}%</span>
                  <span className="text-text-secondary">=</span>
                  <span className="text-accent font-bold">${part.total}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}



const PreviewStep = ({ data, calculatedTotals, onPushToTekmetric, onSendApproval, isPushing, isSending }) => {
  const PreviewRow = ({ label, value, isTotal = false }) => (
    <div
      className={`flex justify-between items-center py-4 ${isTotal ? '' : 'border-b border-border/50'
        }`}
    >
      <p
        className={`font-semibold ${isTotal ? 'text-xl text-text-primary' : 'text-text-secondary'}`}
      >
        {label}
      </p>
      <p
        className={`font-mono font-bold ${isTotal ? 'text-2xl text-text-primary' : 'text-lg text-text-primary'
          }`}
      >
        {value}
      </p>
    </div>
  )

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-text-primary">Estimate Preview</h2>

      {/* Vehicle Info */}
      {data.vehicleInfo && (
        <div className="bg-background p-4 rounded-lg border border-border">
          <h3 className="font-semibold text-text-primary mb-2">Vehicle Information</h3>
          <p className="text-text-secondary">
            {data.vehicleInfo.year} {data.vehicleInfo.make} {data.vehicleInfo.model}
            {data.vehicleInfo.trim && ` ${data.vehicleInfo.trim}`}
          </p>
          <p className="text-xs text-text-secondary mt-1">VIN: {data.vin}</p>
        </div>
      )}

      {/* Customer Info */}
      <div className="bg-background p-4 rounded-lg border border-border">
        <h3 className="font-semibold text-text-primary mb-2">Customer Information</h3>
        <p className="text-text-secondary">{data.customerName}</p>
        {data.customerEmail && <p className="text-xs text-text-secondary">{data.customerEmail}</p>}
        <p className="text-xs text-text-secondary">{data.customerPhone}</p>
      </div>

      {/* Breakdown */}
      <div className="bg-background p-6 rounded-lg border border-border">
        <PreviewRow
          label={`Labor (${data.laborItems.reduce((a, b) => a + parseFloat(b.hours || 0), 0).toFixed(1)}h @ $${data.laborRate}/h)`}
          value={`$${calculatedTotals.laborTotal}`}
        />
        <PreviewRow label="Parts" value={`$${calculatedTotals.partsTotal}`} />
        <PreviewRow label={`Tax (${(data.taxRate * 100).toFixed(1)}%)`} value={`$${calculatedTotals.taxAmount}`} />
        <div className="pt-4">
          <PreviewRow label="Total" value={`$${calculatedTotals.total}`} isTotal={true} />
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-4">
        <button
          onClick={onPushToTekmetric}
          disabled={isPushing}
          className="bg-accent hover:bg-accent-dark text-background font-bold py-3 px-6 rounded-lg transition-all shadow-lg shadow-accent/20 flex items-center justify-center gap-2 w-full sm:w-auto"
        >
          {isPushing ? (
            <>
              <div className="animate-spin h-5 w-5 border-2 border-background border-t-transparent rounded-full"></div>
              Pushing...
            </>
          ) : (
            'Push to Tekmetric'
          )}
        </button>
        <button
          onClick={onSendApproval}
          disabled={isSending}
          className="bg-surface border border-border text-text-secondary font-bold py-3 px-6 rounded-lg hover:bg-primary-light hover:text-text-primary transition-all flex items-center justify-center gap-2 w-full sm:w-auto"
        >
          {isSending ? (
            <>
              <div className="animate-spin h-5 w-5 border-2 border-text-secondary border-t-transparent rounded-full"></div>
              Generating...
            </>
          ) : (
            <>
              <ArrowDownTrayIcon className="h-5 w-5 rotate-180" />
              Send Approval Link
            </>
          )}
        </button>
      </div>
    </div>
  )
}

const ActionsStep = ({ data, calculatedTotals, onDownloadPDF, onSaveDraft }) => {
  const hasData = data.laborItems.length > 0 || data.partsItems.length > 0
  const isReady = hasData

  return (
    <div className="space-y-6 max-w-2xl mx-auto text-center">
      <h2 className="text-2xl font-bold text-text-primary">Actions & Validation</h2>

      {!isReady ? (
        <div className="bg-background p-8 rounded-lg border border-border">
          <p className="text-text-secondary">
            Use Auto-Generate to create the estimate automatically.
          </p>
        </div>
      ) : (
        <>
          <div className="bg-success/10 p-8 rounded-lg border border-success/20 flex flex-col items-center">
            <div className="h-12 w-12 rounded-full bg-success text-background flex items-center justify-center mb-4">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={3}
                stroke="currentColor"
                className="w-6 h-6"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </div>
            <h3 className="text-xl font-bold text-success mb-2">Estimate Ready!</h3>
            <p className="text-text-secondary mb-6">Auto-generated estimate is complete and ready to send.</p>

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row gap-4 w-full justify-center">
              {/* AUTO-SAVE ENABLED: Manual Save button removed */}

              <button
                onClick={onDownloadPDF}
                className="bg-gradient-to-r from-accent to-accent-dark hover:from-accent-dark hover:to-accent text-background font-bold py-4 px-8 rounded-lg transition-all duration-300 flex items-center gap-3 shadow-lg shadow-accent/30 transform hover:scale-105"
              >
                <ArrowDownTrayIcon className="h-6 w-6" />
                Download PDF Estimate
              </button>
            </div>
          </div>

          {/* Estimate Summary */}
          <div className="bg-background p-6 rounded-lg border border-border text-left">
            <h3 className="font-semibold text-text-primary mb-4">Estimate Summary</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-text-secondary">Customer:</span>
                <span className="text-text-primary font-semibold">{data.customerName}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Vehicle:</span>
                <span className="text-text-primary font-semibold">
                  {data.vehicleInfo ? `${data.vehicleInfo.year} ${data.vehicleInfo.make} ${data.vehicleInfo.model}` : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Labor Items:</span>
                <span className="text-text-primary font-semibold">{data.laborItems.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Parts Items:</span>
                <span className="text-text-primary font-semibold">{data.partsItems.length}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-border">
                <span className="text-text-primary font-bold">Total Amount:</span>
                <span className="text-accent font-bold text-lg">${calculatedTotals.total}</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ===================================================================================
//  MAIN NEW ESTIMATE COMPONENT
// ===================================================================================

const steps = ['Intake', 'Labor', 'Parts', 'Vendor Compare', 'Preview', 'Actions']

const NewEstimate = () => {
  const [currentStep, setCurrentStep] = useState(0)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isPushing, setIsPushing] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const contentRef = useRef(null)

  const [formData, setFormData] = useState({
    vin: '',
    serviceRequest: '',
    customerName: '',
    customerEmail: '',
    customerPhone: '',
    odometer: '',
    vehicleInfo: null,
    laborRate: 150,
    taxRate: 0.0925,
    laborItems: [],
    partsItems: [],
  })

  const [calculatedTotals, setCalculatedTotals] = useState({
    laborTotal: '0.00',
    partsTotal: '0.00',
    subtotal: '0.00',
    taxAmount: '0.00',
    cleaningKit: null,
    total: '0.00',
  })

  // New state for enhanced features
  const [vendorData, setVendorData] = useState(null)
  const [flags, setFlags] = useState([])
  const [confidenceScore, setConfidenceScore] = useState(null)

  // Auto-Generate Handler
  const handleAutoGenerate = async () => {
    const canGenerate = formData.vin.length === 17 && formData.serviceRequest && formData.customerName && formData.customerPhone

    if (!canGenerate) {
      alert('Please fill all required fields: VIN (17 chars), Service Request, Customer Name, and Phone')
      return
    }

    setIsGenerating(true)

    const result = await autoGenerateEstimate({
      vin: formData.vin,
      serviceRequest: formData.serviceRequest,
      customerName: formData.customerName,
      customerEmail: formData.customerEmail,
      customerPhone: formData.customerPhone,
      odometer: formData.odometer,
      laborRate: formData.laborRate,
    })

    if (result.success) {
      const responseData = result.data
      const estimateData = responseData.estimate_data

      // Create merged data object for immediate saving
      const mergedData = {
        vin: formData.vin,
        serviceRequest: formData.serviceRequest,
        customerName: formData.customerName,
        customerEmail: formData.customerEmail,
        customerPhone: formData.customerPhone,
        odometer: formData.odometer,
        // Use response data for vehicle info
        vehicleInfo: estimateData.vehicleInfo,
        laborItems: estimateData.laborItems.map((item, idx) => ({
          id: idx + 1,
          description: item.description,
          hours: parseFloat(item.hours),
          rate: parseFloat(item.rate),
          total: item.total,
          source: 'ALLDATA'
        })),
        partsItems: estimateData.partsItems.map((item, idx) => ({
          id: idx + 1,
          description: item.description,
          partNumber: item.partNumber,
          quantity: item.quantity,
          cost: item.cost,
          markup: item.markup,
          total: item.total,
          vendor: item.vendor,
          reasonBadge: item.reason_badge // Map reason badge
        }))
      }

      // Update form data state
      setFormData(prev => ({
        ...prev,
        vehicleInfo: mergedData.vehicleInfo,
        laborItems: mergedData.laborItems,
        partsItems: mergedData.partsItems
      }))

      // Update totals with cleaning kit
      if (estimateData.breakdown) {
        setCalculatedTotals({
          laborTotal: estimateData.breakdown.laborTotal,
          partsTotal: estimateData.breakdown.partsTotal,
          subtotal: estimateData.breakdown.subtotal,
          taxAmount: estimateData.breakdown.taxAmount,
          cleaningKit: estimateData.breakdown.cleaningKit,
          total: estimateData.breakdown.total,
        })
      }

      // Set vendor comparison data
      if (estimateData.vendorComparison) {
        setVendorData(estimateData.vendorComparison)
      }

      // Set flags (recall alerts, warranty alerts, etc.)
      if (responseData.flags && responseData.flags.length > 0) {
        setFlags(responseData.flags)
      }

      // Set confidence score
      if (responseData.confidence_score) {
        setConfidenceScore(responseData.confidence_score)
      }

      autoProgressSteps()

      // AUTO-SAVE: Save to database immediately using mergedData
      await handleSaveDraft(true, mergedData)
    } else {
      alert(`Error: ${result.error}`)
    }

    setIsGenerating(false)
  }

  // Helper to prepare payload
  const prepareEstimatePayload = (dataToUse = formData) => {
    return {
      vin: dataToUse.vin,
      vehicleYear: dataToUse.vehicleInfo?.year,
      vehicleMake: dataToUse.vehicleInfo?.make,
      vehicleModel: dataToUse.vehicleInfo?.model,
      vehicleTrim: dataToUse.vehicleInfo?.trim,
      vehicleEngine: dataToUse.vehicleInfo?.engine,
      odometer: dataToUse.odometer,
      customerFirstName: dataToUse.customerName.split(' ')[0],
      customerLastName: dataToUse.customerName.split(' ').slice(1).join(' ') || '',
      customerEmail: dataToUse.customerEmail,
      customerPhone: dataToUse.customerPhone,
      serviceRequest: dataToUse.serviceRequest,
      laborItems: dataToUse.laborItems,
      partsItems: dataToUse.partsItems
    }
  }

  // Save as Draft Handler
  const handleSaveDraft = async (silent = false, overrideData = null) => {
    if (!silent) setIsPushing(true) // Reuse pushing state or add new one

    const payload = prepareEstimatePayload(overrideData || formData)
    const result = await createDraftEstimate(payload)

    if (result.success) {
      if (!silent) alert(`Estimate Saved! ID: ${result.data.estimateId}`)
      return result.data
    } else {
      if (!silent) alert(`Failed to save draft: ${result.error}`)
      return null
    }
    if (!silent) setIsPushing(false)
  }

  // Push to Tekmetric
  const handlePushToTekmetric = async () => {
    setIsPushing(true)
    const result = await pushToTekmetric({
      customer: {
        name: formData.customerName,
        phone: formData.customerPhone,
        email: formData.customerEmail
      },
      vehicleInfo: formData.vehicleInfo,
      laborItems: formData.laborItems,
      partsItems: formData.partsItems,
      breakdown: calculatedTotals,
      odometer: formData.odometer ? parseInt(formData.odometer) : null
    })

    if (result.success) {
      alert(`Successfully pushed to Tekmetric!\nRO #: ${result.data.tekmetric.ro_number}`)
    } else {
      alert(`Failed to push: ${result.error}`)
    }
    setIsPushing(false)
  }

  // Send Approval Link
  const handleSendApproval = async () => {
    setIsSending(true)

    // 1. Save draft first to get ID
    const savedEstimate = await handleSaveDraft(true) // Silent save

    if (!savedEstimate) {
      alert("Could not save estimate to database. Cannot generate link.")
      setIsSending(false)
      return
    }

    // 2. Generate link with real ID
    const result = await generateApprovalLink(savedEstimate.estimateId, {
      customer: {
        name: formData.customerName,
        phone: formData.customerPhone,
        email: formData.customerEmail
      },
      vehicleInfo: formData.vehicleInfo,
      laborItems: formData.laborItems,
      partsItems: formData.partsItems,
      breakdown: calculatedTotals,
      odometer: formData.odometer
    })

    if (result.success) {
      // In a real app we would email/SMS this. For now just show it.
      const url = result.data.approval_url
      prompt("Approval Link Generated (Copy and send to customer):", url)
    } else {
      alert(`Failed to generate link: ${result.error}`)
    }
    setIsSending(false)
  }

  // Auto-progress through steps
  const autoProgressSteps = () => {
    let step = 1
    const interval = setInterval(() => {
      if (step < steps.length) {
        setCurrentStep(step)
        step++
      } else {
        clearInterval(interval)
      }
    }, 1500)
  }

  // PDF Download Handler
  const handleDownloadPDF = () => {
    const doc = new jsPDF()

    // Header
    doc.setFontSize(20)
    doc.setTextColor(40, 40, 40)
    doc.text('ESTIMATE', 105, 20, { align: 'center' })

    // Company Info (placeholder)
    doc.setFontSize(10)
    doc.setTextColor(100, 100, 100)
    doc.text('German Sport Auto Repair', 105, 28, { align: 'center' })
    doc.text('Professional Estimation System', 105, 33, { align: 'center' })

    // Date
    doc.text(`Date: ${new Date().toLocaleDateString()}`, 14, 45)

    // Customer Info
    doc.setFontSize(12)
    doc.setTextColor(40, 40, 40)
    doc.text('CUSTOMER INFORMATION', 14, 55)
    doc.setFontSize(10)
    doc.setTextColor(60, 60, 60)
    doc.text(`Name: ${formData.customerName}`, 14, 62)
    if (formData.customerEmail) doc.text(`Email: ${formData.customerEmail}`, 14, 68)
    doc.text(`Phone: ${formData.customerPhone}`, 14, 74)

    // Vehicle Info
    if (formData.vehicleInfo) {
      doc.setFontSize(12)
      doc.setTextColor(40, 40, 40)
      doc.text('VEHICLE INFORMATION', 14, 85)
      doc.setFontSize(10)
      doc.setTextColor(60, 60, 60)
      doc.text(`${formData.vehicleInfo.year} ${formData.vehicleInfo.make} ${formData.vehicleInfo.model}`, 14, 92)
      doc.text(`VIN: ${formData.vin}`, 14, 98)
      if (formData.odometer) doc.text(`Odometer: ${formData.odometer} km`, 14, 104)
    }

    // Service Request
    doc.setFontSize(12)
    doc.setTextColor(40, 40, 40)
    doc.text('SERVICE REQUEST', 14, 115)
    doc.setFontSize(10)
    doc.setTextColor(60, 60, 60)
    doc.text(formData.serviceRequest, 14, 122)

    let currentY = 135

    // Labor Items Table
    if (formData.laborItems.length > 0) {
      autoTable(doc, {
        startY: currentY,
        head: [['Labor Description', 'Hours', 'Rate', 'Total']],
        body: formData.laborItems.map(item => [
          item.description,
          `${item.hours}h`,
          `$${item.rate}/hr`,
          `$${item.total}`
        ]),
        theme: 'striped',
        headStyles: { fillColor: [41, 128, 185] }
      })
      currentY = doc.lastAutoTable.finalY + 10
    }

    // Parts Items Table
    if (formData.partsItems.length > 0) {
      autoTable(doc, {
        startY: currentY,
        head: [['Part Description', 'Part #', 'Qty', 'Price', 'Total']],
        body: formData.partsItems.map(item => [
          item.description,
          item.partNumber || 'N/A',
          item.quantity,
          `$${item.cost}`,
          `$${item.total}`
        ]),
        theme: 'striped',
        headStyles: { fillColor: [41, 128, 185] }
      })
      currentY = doc.lastAutoTable.finalY + 15
    }

    // Totals
    doc.setFontSize(10)
    doc.text(`Labor Total:`, 130, currentY)
    doc.text(`$${calculatedTotals.laborTotal}`, 180, currentY, { align: 'right' })

    doc.text(`Parts Total:`, 130, currentY + 6)
    doc.text(`$${calculatedTotals.partsTotal}`, 180, currentY + 6, { align: 'right' })

    doc.text(`Subtotal:`, 130, currentY + 12)
    doc.text(`$${calculatedTotals.subtotal}`, 180, currentY + 12, { align: 'right' })

    doc.text(`Tax (${(formData.taxRate * 100).toFixed(1)}%):`, 130, currentY + 18)
    doc.text(`$${calculatedTotals.taxAmount}`, 180, currentY + 18, { align: 'right' })

    doc.setFontSize(12)
    doc.setFont(undefined, 'bold')
    doc.text(`TOTAL:`, 130, currentY + 26)
    doc.text(`$${calculatedTotals.total}`, 180, currentY + 26, { align: 'right' })

    // Footer
    doc.setFontSize(8)
    doc.setFont(undefined, 'normal')
    doc.setTextColor(150, 150, 150)
    doc.text('This estimate is valid for 30 days from the date of issue.', 105, 280, { align: 'center' })

    // Save PDF
    doc.save(`Estimate_${formData.customerName.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.pdf`)
  }

  const updateData = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const animateStep = () => {
    if (contentRef.current) {
      gsap.fromTo(
        contentRef.current,
        { opacity: 0, x: 20 },
        { opacity: 1, x: 0, duration: 0.4, ease: 'power2.out' },
      )
    }
  }

  useEffect(() => {
    animateStep()
  }, [currentStep])

  const renderStepContent = () => {
    switch (currentStep) {
      case 0:
        return <IntakeStep data={formData} updateData={updateData} />
      case 1:
        return <LaborStep data={formData} />
      case 2:
        return <PartsStep data={formData} />
      case 3:
        return <VendorCompareStep vendorData={vendorData} />
      case 4:
        return <PreviewStep
          data={formData}
          calculatedTotals={calculatedTotals}
          onPushToTekmetric={handlePushToTekmetric}
          onSendApproval={handleSendApproval}
          isPushing={isPushing}
          isSending={isSending}
        />
      case 5:
        return <ActionsStep
          data={formData}
          calculatedTotals={calculatedTotals}
          onDownloadPDF={handleDownloadPDF}
          onSaveDraft={() => handleSaveDraft(false)}
        />
      default:
        return <IntakeStep data={formData} updateData={updateData} />
    }
  }

  return (
    <div className="p-4 md:p-8 min-h-full flex flex-col">
      {/* Top Section: Stepper */}
      <div className="flex flex-col sm:flex-row justify-between items-center mb-8 gap-4">
        <div className="flex items-center space-x-2 md:space-x-4 overflow-x-auto w-full sm:w-auto pb-2 sm:pb-0">
          {steps.map((step, index) => (
            <div key={index} className="flex items-center flex-shrink-0">
              <div
                className={`flex items-center justify-center w-8 h-8 rounded-full font-bold transition-all duration-300 ${currentStep === index
                  ? 'bg-accent text-background scale-110 shadow-lg shadow-accent/30'
                  : currentStep > index
                    ? 'bg-success text-background'
                    : 'bg-surface border-2 border-border text-text-secondary'
                  }`}
              >
                {currentStep > index ? '✓' : index + 1}
              </div>
              <span
                className={`ml-3 hidden md:block font-semibold text-sm ${currentStep === index ? 'text-text-primary' : 'text-text-secondary'
                  }`}
              >
                {step}
              </span>
              {index < steps.length - 1 && (
                <div className="w-4 h-0.5 bg-border mx-2 hidden md:block"></div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-grow bg-surface border border-border rounded-xl p-6 md:p-8 shadow-2xl">
        <div ref={contentRef}>{renderStepContent()}</div>
      </div>

      {/* Bottom: Auto-Generate Button */}
      {/* Bottom: Navigation & Actions */}
      <div className="flex justify-between items-center w-full max-w-4xl px-4 mt-8 mx-auto">
        <button
          onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}
          disabled={currentStep === 0}
          className={`px-6 py-3 rounded-lg font-semibold transition-all ${currentStep === 0
            ? 'bg-surface border border-border text-text-secondary opacity-50 cursor-not-allowed'
            : 'bg-surface border border-border text-text-primary hover:bg-primary-light hover:border-accent/50'
            }`}
        >
          ← Back
        </button>

        {currentStep === 0 && (
          <button
            onClick={handleAutoGenerate}
            disabled={isGenerating}
            className="bg-gradient-to-r from-accent to-accent-dark hover:from-accent-dark hover:to-accent text-background font-bold px-12 py-3 rounded-lg transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-3 shadow-lg shadow-accent/30 transform hover:scale-105"
          >
            {isGenerating ? (
              <>
                <div className="animate-spin h-6 w-6 border-2 border-background border-t-transparent rounded-full"></div>
                Generating...
              </>
            ) : (
              <>
                <SparklesIcon className="h-6 w-6" />
                Auto-Generate
              </>
            )}
          </button>
        )}

        <button
          onClick={() => setCurrentStep(Math.min(steps.length - 1, currentStep + 1))}
          disabled={currentStep === steps.length - 1}
          className={`px-6 py-3 rounded-lg font-semibold transition-all ${currentStep === steps.length - 1
            ? 'bg-surface border border-border text-text-secondary opacity-50 cursor-not-allowed'
            : 'bg-accent text-background hover:bg-accent-dark shadow-lg shadow-accent/20'
            }`}
        >
          Next →
        </button>
      </div>
    </div>
  )
}

export default NewEstimate
