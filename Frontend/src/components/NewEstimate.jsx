import React, { useState, useRef, useEffect } from 'react'
import { gsap } from 'gsap'
import { ExclamationCircleIcon, TrashIcon, PlusIcon, SparklesIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline'
import { autoGenerateEstimate, submitAutoGenJob, pollAutoGenJob, pushToTekmetric, pollTekmetricJob, generateApprovalLink, createDraftEstimate, updateEstimate } from '../services/api'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import VendorCompareStep from './estimate-steps/VendorCompareStep'
import { useToast } from './ui/Toast'

// ===================================================================================
//  HELPERS
// ===================================================================================

// Transform the backend's vendorQuotes + vendorComparison into the shape
// VendorCompareStep expects. Backend returns one VendorQuote per offer
// (vendor/brand/price/in_stock) grouped under `vendorComparison[requested_part]
// = {best, all}`. The UI groups by requested part and ranks offers by price
// with the best (cheapest in-stock) flagged.
const transformVendorData = (vendorComparison, vendorQuotes = []) => {
  if (!vendorComparison || Object.keys(vendorComparison).length === 0) return null

  const parts = Object.entries(vendorComparison)
    .map(([requestedPart, info]) => {
      const all = (info && info.all) || []
      const best = (info && info.best) || null
      const priced = all.filter((q) => q && q.found && q.price != null)
      if (priced.length === 0) return null

      const cheapestPrice = Math.min(...priced.map((q) => parseFloat(q.price)))
      const dearestPrice = Math.max(...priced.map((q) => parseFloat(q.price)))
      const offers = priced
        .map((q) => {
          const isCheapest =
            best && q.vendor === best.vendor && parseFloat(q.price) === parseFloat(best.price)
          const brandLabel = (q.brand || '').toString()
          const isOem = /genuine|oem/i.test(brandLabel)
          const composite =
            cheapestPrice && parseFloat(q.price)
              ? Math.round((cheapestPrice / parseFloat(q.price)) * 100)
              : 0
          return {
            vendor_name: q.vendor,
            brand: brandLabel || '—',
            brand_tier: isOem ? 'OEM' : 'Aftermarket',
            price: q.price,
            stock_status:
              q.in_stock === true ? 'In Stock' : q.in_stock === false ? 'Out of Stock' : 'Unknown',
            stock_quantity: q.availability || (q.in_stock ? 'Available' : ''),
            distance_miles: '—',
            scores: { composite },
            is_cheapest: !!isCheapest,
            selection: isCheapest ? 'Primary' : 'Backup',
          }
        })
        .sort((a, b) => parseFloat(a.price) - parseFloat(b.price))

      return {
        description: best?.matched_part_name || requestedPart,
        part_number: best?.oem_number || requestedPart,
        offers,
        savings: dearestPrice - cheapestPrice,
      }
    })
    .filter(Boolean)

  if (parts.length === 0) return null

  const vendorsQueried = Array.from(new Set(vendorQuotes.map((q) => q.vendor).filter(Boolean)))
  return {
    parts,
    weights: { brand: 40, price: 35, distance: 25 },
    summary: {
      vendors_queried: vendorsQueried,
      note: `Live pricing across ${vendorsQueried.length || 0} vendor(s) — best price selected`,
    },
  }
}

// ===================================================================================
//  STEP COMPONENTS
// ===================================================================================

// InputField is defined OUTSIDE IntakeStep to prevent re-mounting on every keystroke
const InputField = ({ label, placeholder, value, fieldKey, type = "text", required = false, updateData }) => (
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

const IntakeStep = ({ data, updateData }) => {

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
          updateData={updateData}
        />
        <InputField
          label="Service Request"
          placeholder="e.g., Brake pads, Oil change"
          value={data.serviceRequest}
          fieldKey="serviceRequest"
          required
          updateData={updateData}
        />
        <InputField
          label="Customer Name"
          placeholder="Full name"
          value={data.customerName}
          fieldKey="customerName"
          required
          updateData={updateData}
        />
        <InputField
          label="Customer Email"
          placeholder="email@example.com"
          value={data.customerEmail}
          fieldKey="customerEmail"
          type="email"
          updateData={updateData}
        />
        <InputField
          label="Customer Phone"
          placeholder="+1-555-123-4567"
          value={data.customerPhone}
          fieldKey="customerPhone"
          required
          updateData={updateData}
        />
        <InputField
          label="Odometer (km)"
          placeholder="Optional"
          value={data.odometer}
          fieldKey="odometer"
          type="number"
          updateData={updateData}
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

const ActionsStep = ({ data, calculatedTotals, onDownloadPDF, onSaveDraft, onPushToTekmetric, isPushing, tekmetricProgress, tekmetricResult }) => {
  const hasData = data.laborItems.length > 0 || data.partsItems.length > 0
  const isReady = hasData

  return (
    <div className="space-y-6 max-w-2xl mx-auto text-center">
      <h2 className="text-2xl font-bold text-text-primary">Actions & Validation</h2>

      {/* Live Tekmetric push progress — appears as soon as a job is enqueued
          and disappears when the agent reports a final RO (or a failure). */}
      {tekmetricProgress && (
        <div className="bg-surface p-5 rounded-lg border border-primary/40 text-left">
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full bg-accent animate-pulse" />
              <span className="font-bold text-text-primary">Tekmetric Agent — Live</span>
              {tekmetricProgress.jobId && (
                <code className="text-xs bg-background px-2 py-0.5 rounded text-text-secondary">
                  {tekmetricProgress.jobId}
                </code>
              )}
            </div>
            <span className="text-xs uppercase tracking-wider text-text-secondary">
              {tekmetricProgress.status}
            </span>
          </div>
          <p className="text-sm text-text-secondary mb-3">{tekmetricProgress.progress}</p>
          <div className="h-2 bg-background rounded-full overflow-hidden">
            <div
              className="h-full bg-accent transition-all duration-500"
              style={{ width: `${tekmetricProgress.progress_pct || 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Final RO# card — appears after a successful push. Acts as the
          handoff: advisor clicks the link to finish in Tekmetric. */}
      {tekmetricResult?.ro_number && (
        <div className="bg-success/10 p-5 rounded-lg border border-success/30 text-left">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-success font-semibold mb-1">
                ✓ Pushed to Tekmetric
              </p>
              <p className="text-2xl font-bold text-text-primary font-mono">
                RO #{tekmetricResult.ro_number}
              </p>
              <p className="text-xs text-text-secondary mt-2">
                Customer: {tekmetricResult.customer_action === 'created_new' ? 'created new' : 'matched existing'}
                {' · '}
                Vehicle: {tekmetricResult.vehicle_action === 'created_new' ? 'created new' : 'matched existing'}
                {' · '}
                {(tekmetricResult.labor_lines_added ?? '?')} labor / {(tekmetricResult.parts_lines_added ?? '?')} parts lines
              </p>
              {tekmetricResult.note && (
                <p className="text-xs text-warning mt-2">{tekmetricResult.note}</p>
              )}
            </div>
            {tekmetricResult.ro_url && (
              <a
                href={tekmetricResult.ro_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 bg-accent text-background font-bold rounded-lg hover:bg-accent/80 transition-colors whitespace-nowrap"
              >
                Open in Tekmetric →
              </a>
            )}
          </div>
        </div>
      )}

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
                onClick={onPushToTekmetric}
                disabled={isPushing}
                className="bg-gradient-to-r from-primary to-primary-dark hover:from-primary-dark hover:to-primary text-white font-bold py-4 px-8 rounded-lg transition-all duration-300 flex items-center gap-3 shadow-lg shadow-primary/30 transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isPushing ? (
                  <>
                    <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                    Pushing...
                  </>
                ) : (
                  <>
                    <ArrowDownTrayIcon className="h-6 w-6 rotate-180" />
                    Push to Tekmetric
                  </>
                )}
              </button>

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
  const toast = useToast()
  const [currentStep, setCurrentStep] = useState(0)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isPushing, setIsPushing] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const contentRef = useRef(null)

  const [formData, setFormData] = useState({
    estimateId: null,
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

  // Live agent progress state (new queue-based flow)
  const [agentProgress, setAgentProgress] = useState(null)
  // shape: { jobId, status, progress, progress_pct }

  // Tekmetric write-back progress + final RO link
  const [tekmetricProgress, setTekmetricProgress] = useState(null)
  const [tekmetricResult, setTekmetricResult] = useState(null)
  // tekmetricResult shape: { ro_number, ro_url, customer_action, vehicle_action,
  //                          labor_lines_added, parts_lines_added, note }

  // Auto-Generate Handler — NEW queue-based flow (frontend → backend → VPS agent)
  const handleAutoGenerate = async () => {
    const canGenerate =
      formData.vin.length === 17 &&
      formData.serviceRequest &&
      formData.customerName &&
      formData.customerPhone

    if (!canGenerate) {
      toast.error('Please fill all required fields: VIN (17 chars), Service Request, Customer Name, and Phone')
      return
    }

    setIsGenerating(true)
    setAgentProgress({ jobId: null, status: 'queued', progress: 'Submitting…', progress_pct: 2 })

    // 1. Submit the job
    const submit = await submitAutoGenJob({
      vin: formData.vin,
      serviceRequest: formData.serviceRequest,
      customerName: formData.customerName,
      customerEmail: formData.customerEmail,
      customerPhone: formData.customerPhone,
      odometer: formData.odometer,
      laborRate: formData.laborRate,
      taxRate: formData.taxRate,
    })

    if (!submit.success) {
      toast.error(submit.error || 'Failed to submit job', 'Error')
      setIsGenerating(false)
      setAgentProgress(null)
      return
    }

    const jobId = submit.data.job_id
    setAgentProgress({
      jobId,
      status: submit.data.status,
      progress: submit.data.progress,
      progress_pct: submit.data.progress_pct,
    })

    // 2. Poll until terminal
    const poll = await pollAutoGenJob(jobId, {
      intervalMs: 2500,
      timeoutMs: 600000,
      onProgress: (job) =>
        setAgentProgress({
          jobId: job.job_id,
          status: job.status,
          progress: job.progress,
          progress_pct: job.progress_pct,
        }),
    })

    if (!poll.success) {
      toast.error(poll.error || 'Polling failed', 'Error')
      setIsGenerating(false)
      return
    }

    const job = poll.data

    if (job.status === 'failed') {
      toast.error(job.error || 'Agent failed to complete the estimate', 'Generation Failed')
      setIsGenerating(false)
      return
    }

    // 3. Success — populate state from the agent result
    const r = job.result || {}
    const veh = r.vehicleInfo || {}
    const laborItems = (r.laborItems || []).map((item, idx) => ({
      id: idx + 1,
      description: item.description,
      hours: parseFloat(item.hours),
      rate: parseFloat(item.rate),
      total: parseFloat(item.total).toFixed(2),
      source: item.source || 'ALLDATA',
      skill: item.skill,
    }))
    const partsItems = (r.partsItems || []).map((item, idx) => ({
      id: idx + 1,
      description: item.description,
      partNumber: item.partNumber,
      quantity: item.quantity,
      cost: item.cost,
      markup: item.markup,
      total: parseFloat(item.total).toFixed(2),
      vendor: item.vendor || 'ALLDATA',
    }))

    const mergedData = {
      vin: formData.vin,
      serviceRequest: formData.serviceRequest,
      customerName: formData.customerName,
      customerEmail: formData.customerEmail,
      customerPhone: formData.customerPhone,
      odometer: formData.odometer,
      vehicleInfo: veh,
      laborItems,
      partsItems,
    }

    setFormData((prev) => ({
      ...prev,
      vehicleInfo: veh,
      laborItems,
      partsItems,
    }))

    const bd = r.breakdown || {}
    setCalculatedTotals({
      laborTotal: (bd.laborTotal ?? 0).toFixed(2),
      partsTotal: (bd.partsTotal ?? 0).toFixed(2),
      subtotal: (bd.subtotal ?? 0).toFixed(2),
      taxAmount: (bd.taxAmount ?? 0).toFixed(2),
      cleaningKit: null,
      total: (bd.total ?? 0).toFixed(2),
    })

    setConfidenceScore({
      extraction: r.extraction_confidence ?? null,
      verification: r.verification_confidence ?? null,
      verification_match: r.verification_match ?? null,
      verification_reason: r.verification_reason ?? null,
      section_path: r.section_path ?? null,
      agent_steps: r.agent_steps ?? null,
      elapsed_sec: r.elapsed_sec ?? null,
    })

    // Hydrate the Vendor Compare step with the live Worldpac/SSF quotes the
    // worker produced. Null means "no live quotes returned" and the step
    // shows its placeholder instead of fake rows.
    setVendorData(transformVendorData(r.vendorComparison, r.vendorQuotes || []))

    autoProgressSteps()
    await handleSaveDraft(true, mergedData)

    setIsGenerating(false)
    setAgentProgress(null)
    toast.success(
      `Estimate ready: ${laborItems.length} labor item(s), ${partsItems.length} part(s)`,
      'Done'
    )
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

  // Save as Draft (or Update) Handler
  const handleSaveDraft = async (silent = false, overrideData = null) => {
    if (!silent) setIsPushing(true)

    const payload = prepareEstimatePayload(overrideData || formData)

    let result
    if (formData.estimateId) {
      // UPDATE existing estimate
      result = await updateEstimate(formData.estimateId, payload)
    } else {
      // CREATE new estimate
      result = await createDraftEstimate(payload)
    }

    if (result.success) {
      // Store the ID so subsequent saves are updates
      const newId = result.data.estimateId
      if (!formData.estimateId) {
        setFormData(prev => ({ ...prev, estimateId: newId }))
      }

      if (!silent) alert(`Estimate Saved! ID: ${newId}`)
      if (!silent) setIsPushing(false)
      return result.data
    } else {
      if (!silent) alert(`Failed to save draft: ${result.error}`)
      if (!silent) setIsPushing(false)
      return null
    }
  }

  // Push to Tekmetric — queue-based via the VPS vision agent.
  //
  // Why this changed: the old code POSTed once and trusted the response.
  // When the backend's REST stub had no API key it returned a mocked
  // "success" with a fabricated RO number, so the UI confirmed a push that
  // never actually happened. The new flow enqueues a job that the worker
  // runs in the shop's logged-in Tekmetric tab, then polls for the real
  // RO# the agent captured.
  const handlePushToTekmetric = async () => {
    if (!formData.laborItems?.length && !formData.partsItems?.length) {
      toast.error('Add labor or parts before pushing to Tekmetric', 'Nothing to push')
      return
    }
    setIsPushing(true)
    setTekmetricProgress({ jobId: null, status: 'queued', progress: 'Submitting…', progress_pct: 2 })

    const submit = await pushToTekmetric({
      customer: {
        name: formData.customerName,
        phone: formData.customerPhone,
        email: formData.customerEmail,
      },
      vehicleInfo: formData.vehicleInfo,
      laborItems: formData.laborItems,
      partsItems: formData.partsItems,
      breakdown: calculatedTotals,
      odometer: formData.odometer ? parseInt(formData.odometer) : null,
      estimateId: formData.estimateId || undefined,
    })

    if (!submit.success) {
      toast.error(submit.error || 'Failed to enqueue Tekmetric push', 'Push failed')
      setIsPushing(false)
      setTekmetricProgress(null)
      return
    }

    const jobId = submit.data.job_id
    setTekmetricProgress({
      jobId,
      status: submit.data.status,
      progress: submit.data.progress,
      progress_pct: submit.data.progress_pct,
    })

    const poll = await pollTekmetricJob(jobId, {
      intervalMs: 2500,
      timeoutMs: 600000,
      onProgress: (job) =>
        setTekmetricProgress({
          jobId: job.job_id,
          status: job.status,
          progress: job.progress,
          progress_pct: job.progress_pct,
        }),
    })

    setIsPushing(false)

    if (!poll.success) {
      toast.error(poll.error || 'Polling failed', 'Push failed')
      setTekmetricProgress(null)
      return
    }

    const job = poll.data
    if (job.status === 'failed') {
      toast.error(job.error || 'Tekmetric agent could not complete the push', 'Push failed')
      setTekmetricProgress({ ...job, error: job.error })
      return
    }

    const ro = job.result || {}
    setTekmetricResult({
      ro_number: ro.ro_number,
      ro_url: ro.ro_url,
      customer_action: ro.customer_action,
      vehicle_action: ro.vehicle_action,
      labor_lines_added: ro.labor_lines_added,
      parts_lines_added: ro.parts_lines_added,
      note: ro.note,
    })
    setTekmetricProgress(null)
    toast.success(
      `Created RO #${ro.ro_number} in Tekmetric` +
        (ro.customer_action === 'created_new' ? ' (new customer)' : '') +
        (ro.vehicle_action === 'created_new' ? ' (new vehicle)' : ''),
      'Pushed',
    )
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
          onPushToTekmetric={handlePushToTekmetric}
          isPushing={isPushing}
          tekmetricProgress={tekmetricProgress}
          tekmetricResult={tekmetricResult}
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

      {/* Live agent progress panel */}
      {(isGenerating || agentProgress) && (
        <div className="w-full max-w-4xl mx-auto mb-4 bg-surface border border-accent/40 rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="relative h-3 w-3">
                <span className="absolute inline-flex h-full w-full rounded-full bg-accent opacity-75 animate-ping"></span>
                <span className="relative inline-flex h-3 w-3 rounded-full bg-accent"></span>
              </div>
              <span className="text-sm font-semibold text-text-primary tracking-wide">
                ALLDATA Agent — Live
              </span>
              {agentProgress?.jobId && (
                <span className="text-[11px] font-mono text-text-secondary bg-background px-2 py-0.5 rounded border border-border">
                  {agentProgress.jobId}
                </span>
              )}
            </div>
            <span className="text-xs uppercase tracking-wider text-text-secondary">
              {agentProgress?.status || 'queued'}
            </span>
          </div>
          <p className="text-sm text-text-secondary mb-3 min-h-[20px]">
            {agentProgress?.progress || 'Submitting job to backend…'}
          </p>
          <div className="w-full h-2 bg-background rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-accent to-accent-dark transition-all duration-700 ease-out"
              style={{ width: `${agentProgress?.progress_pct ?? 5}%` }}
            />
          </div>
        </div>
      )}

      {/* Confidence + traceability badge once agent result lands */}
      {confidenceScore && !isGenerating && (formData.laborItems.length > 0 || formData.partsItems.length > 0) && (
        <div className="w-full max-w-4xl mx-auto mb-4 bg-surface border border-border rounded-xl p-5">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${
                (confidenceScore.verification_confidence ?? 0) >= 0.9 ? 'bg-success' :
                (confidenceScore.verification_confidence ?? 0) >= 0.7 ? 'bg-warning' : 'bg-danger'
              }`}></span>
              <span className="text-text-secondary">Confidence:</span>
              <span className="font-semibold text-text-primary">
                {confidenceScore.verification_confidence != null
                  ? `${Math.round(confidenceScore.verification_confidence * 100)}%`
                  : '—'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-text-secondary">Match:</span>
              <span className={`font-semibold ${confidenceScore.verification_match ? 'text-success' : 'text-danger'}`}>
                {confidenceScore.verification_match ? 'Yes' : 'No'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-text-secondary">Agent steps:</span>
              <span className="font-semibold text-text-primary">{confidenceScore.agent_steps ?? '—'}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-text-secondary">Elapsed:</span>
              <span className="font-semibold text-text-primary">
                {confidenceScore.elapsed_sec != null ? `${confidenceScore.elapsed_sec.toFixed(1)}s` : '—'}
              </span>
            </div>
          </div>
          {confidenceScore.section_path && (
            <p className="text-xs text-text-secondary mt-2 font-mono">
              <span className="text-text-secondary/70">Source path: </span>{confidenceScore.section_path}
            </p>
          )}
          {confidenceScore.verification_reason && (
            <p className="text-xs text-text-secondary mt-1 italic">
              Hermes: {confidenceScore.verification_reason}
            </p>
          )}
        </div>
      )}

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
