import React, { useState, useRef, useEffect } from 'react'
import { gsap } from 'gsap'
import { ExclamationCircleIcon, TrashIcon, PlusIcon, SparklesIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline'
import { autoGenerateEstimate, submitAutoGenJob, pollAutoGenJob, getAutoGenJob, pushToTekmetric, pollTekmetricJob, generateApprovalLink, createDraftEstimate, updateEstimate } from '../services/api'
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
// OEM-style numbers come back with varying punctuation across vendors
// (`007 420 92 20` vs `0074209220`). Strip whitespace + dashes for the
// dedup key so the same SKU listed twice isn't counted as two offers.
const _normOemForFE = (s) => {
  if (s == null) return ''
  return String(s).replace(/[\s\-_./,]+/g, '').toUpperCase()
}

const transformVendorData = (vendorComparison, vendorQuotes = []) => {
  if (!vendorComparison || Object.keys(vendorComparison).length === 0) return null

  // Track whether ANY priced offer carries real distance data. SSF/Worldpac
  // currently don't, so the Distance column ends up "—" for every row AND
  // the 25% weight goes unused. When this stays false the FE hides the
  // column and rebalances the weights display so the advisor doesn't see
  // a quarter of the score allocated to nothing.
  let anyDistance = false

  const parts = Object.entries(vendorComparison)
    .map(([requestedPart, info]) => {
      const all = (info && info.all) || []
      const best = (info && info.best) || null
      const priced = all.filter((q) => q && q.found && q.price != null)
      if (priced.length === 0) return null

      // Dedup priced rows. SSF in particular returns the same brand twice
      // (once per wheel-variant the catalog labels separately) with
      // identical vendor/brand/SKU/price/stock — surfacing both as
      // distinct offers makes the comparison grid noisy and inflates the
      // "Sources: X/Y" denominator. Key on what the advisor would actually
      // treat as the same listing.
      const seen = new Set()
      const dedupedPriced = []
      for (const q of priced) {
        const key = [
          q.vendor || '',
          (q.brand || '').toString().toLowerCase(),
          _normOemForFE(q.oem_number),
          // round price to cents so $58.770000001 vs $58.77 don't split
          Math.round(parseFloat(q.price) * 100),
          q.in_stock === true ? '1' : q.in_stock === false ? '0' : '?',
        ].join('|')
        if (seen.has(key)) continue
        seen.add(key)
        dedupedPriced.push(q)
      }

      const cheapestPrice = Math.min(...dedupedPriced.map((q) => parseFloat(q.price)))
      const dearestPrice = Math.max(...dedupedPriced.map((q) => parseFloat(q.price)))
      const offers = dedupedPriced
        .map((q) => {
          const isCheapest =
            best && q.vendor === best.vendor && parseFloat(q.price) === parseFloat(best.price)
          const brandLabel = (q.brand || '').toString()
          const isOem = /genuine|oem/i.test(brandLabel)
          const composite =
            cheapestPrice && parseFloat(q.price)
              ? Math.round((cheapestPrice / parseFloat(q.price)) * 100)
              : 0
          // Real distance when the vendor reports it (numeric or "X mi"
          // string). Anything else gets the "—" placeholder and DOESN'T
          // flip anyDistance — so a vendor that's just missing the field
          // for everyone doesn't lock the column open.
          let distance = '—'
          if (q.distance_miles != null && q.distance_miles !== '') {
            const num = parseFloat(q.distance_miles)
            if (!Number.isNaN(num)) {
              distance = num
              anyDistance = true
            }
          }
          return {
            vendor_name: q.vendor,
            brand: brandLabel || '—',
            brand_tier: isOem ? 'OEM' : 'Aftermarket',
            price: q.price,
            stock_status:
              q.in_stock === true ? 'In Stock' : q.in_stock === false ? 'Out of Stock' : 'Unknown',
            stock_quantity: q.availability || (q.in_stock ? 'Available' : ''),
            distance_miles: distance,
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

  // Collect vendors that were called but didn't return a priced row, with the
  // operator-readable note the worker attached. Without this the UI silently
  // drops failed vendors and the advisor wonders why "Vendors Queried" lists
  // three names but only one shows up in the price race.
  const vendorsQueried = Array.from(new Set(vendorQuotes.map((q) => q.vendor).filter(Boolean)))
  const failures = []
  const seenFailureVendors = new Set()
  for (const q of vendorQuotes) {
    if (!q || q.found || !q.vendor) continue
    if (seenFailureVendors.has(q.vendor)) continue
    seenFailureVendors.add(q.vendor)
    failures.push({
      vendor: q.vendor,
      note: q.note || 'no quote returned',
      reason: describeVendorFailure(q.note),
    })
  }
  const successfulVendors = vendorsQueried.filter((v) => !seenFailureVendors.has(v))

  // When no offer carried real distance data the 25% weight is allocated
  // to a tied-zero column for everyone — meaningless. Rebalance to a
  // Brand+Price split (53 / 47, preserving the original 40:35 ratio) and
  // flag distance hidden so the table can collapse the column.
  const weights = anyDistance
    ? { brand: 40, price: 35, distance: 25, distance_available: true }
    : { brand: 53, price: 47, distance: 0, distance_available: false }

  return {
    parts,
    weights,
    summary: {
      vendors_queried: vendorsQueried,
      successful_vendors: successfulVendors,
      failures,
      note: failures.length
        ? `${successfulVendors.length} vendor(s) returned prices; ${failures.length} unavailable this run`
        : `Live pricing across ${vendorsQueried.length || 0} vendor(s) — best price selected`,
    },
  }
}

// Short, advisor-readable summary of why a vendor returned no quote — keeps
// the surfacing useful without dumping a stack trace into the UI.
//
// Order matters: SPECIFIC tokens come before GENERIC ones, otherwise
// `low.includes('timeout')` swallows every more-specific failure (a
// vehicle_set_failed bubbles up as a TimeoutError from Playwright, but the
// advisor needs to see that the *vehicle* couldn't be set, not that the
// vendor site was generically slow — they're very different problems).
const describeVendorFailure = (note) => {
  if (!note) return 'No quote returned'
  const low = String(note).toLowerCase()
  if (low.includes('session_expired') || low.includes('login_failed') || low.includes('login_required'))
    return 'Session expired — please log in via VPS console'
  if (low.includes('skipped')) {
    // Portal explicitly declined this run (e.g. "VOLVO not covered by
    // PartsLink24"). Surface the reason verbatim, it's already short.
    const reason = String(note).split('skipped ::').pop().trim().slice(0, 120)
    return reason ? `Skipped — ${reason}` : 'Skipped by vendor'
  }
  if (low.includes('vehicle_set_failed') || low.includes('year_pick_failed') ||
      low.includes('picker_open_failed'))
    return 'Vehicle not available on this vendor (year / make / model could not be selected in their catalog)'
  if (low.includes('no_brand_app')) return 'Vendor does not cover this make'
  if (low.includes('row_not_found') || low.includes('unmapped_part_type'))
    return 'No matching catalog row for this part type'
  if (low.includes('prep_failed')) return 'Vendor page did not load correctly'
  // Generic timeout AFTER the specific vehicle/picker timeouts above — only
  // matches when the failure really was the vendor site being slow.
  if (low.includes('timeout')) return 'Timed out — vendor site was slow'
  return String(note).slice(0, 120)
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
  // Per-row "View source" toggle. Map of index → bool. We keep it local
  // because the source screenshot is purely informational and shouldn't
  // round-trip through Redux/parent state.
  const [openSource, setOpenSource] = useState({})
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
          {data.laborItems.map((item, index) => {
            const hasTrail = !!item.extractionScreenshot
            const isOpen = !!openSource[index]
            return (
              <div
                key={index}
                className="bg-background p-4 rounded-lg border border-border"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <p className="font-semibold text-text-primary">{item.description}</p>
                    <p className="text-xs text-text-secondary">
                      Source: {item.source || 'ALLDATA'}
                      {hasTrail && (
                        <>
                          {' '}·{' '}
                          <button
                            type="button"
                            onClick={() => setOpenSource((s) => ({ ...s, [index]: !s[index] }))}
                            className="underline hover:text-text-primary"
                          >
                            {isOpen ? 'Hide source screenshot' : 'View source screenshot'}
                          </button>
                        </>
                      )}
                    </p>
                    {item.determinism_status && item.determinism_status !== 'no_skeleton' && (() => {
                      const ds = item.determinism_status
                      const style =
                        ds === 'matched_preferred' ? { chip: 'bg-success/15 text-success border-success/40', label: 'Canonical pick' }
                        : ds === 'matched_fallback' ? { chip: 'bg-info/15 text-info border-info/40', label: `Fallback pick (priority ${item.determinism_rank ?? '?'})` }
                        : { chip: 'bg-warning/15 text-warning border-warning/40', label: 'Off-script row' }
                      return (
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 mt-1 rounded-full border text-[10px] font-medium ${style.chip}`}
                          title={item.determinism_preferred ? `Skeleton preferred row: "${item.determinism_preferred}"` : ''}
                        >
                          {style.label}
                          {item.determinism_preferred && ds !== 'matched_preferred' && (
                            <span className="opacity-70">· expected "{item.determinism_preferred}"</span>
                          )}
                        </span>
                      )
                    })()}
                    {item.auto_added && (
                      <span className="inline-block mt-1 ml-2 px-2 py-0.5 bg-info/15 text-info text-[10px] rounded border border-info/30">
                        Auto-added{item.auto_added_reason ? ` — ${item.auto_added_reason}` : ''}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="text-text-primary font-semibold">{item.hours}h</span>
                    <span className="text-text-secondary">×</span>
                    <span className="text-text-primary font-semibold">${item.rate}/hr</span>
                    <span className="text-text-secondary">=</span>
                    <span className="text-accent font-bold">${item.total}</span>
                  </div>
                </div>
                {hasTrail && isOpen && (
                  <div className="mt-3 pt-3 border-t border-border/50">
                    <p className="text-xs text-text-secondary mb-2">
                      ALLDATA Parts &amp; Labor page captured at extraction time
                    </p>
                    <img
                      src={item.extractionScreenshot}
                      alt={`ALLDATA source for ${item.description}`}
                      className="w-full rounded border border-border"
                      loading="lazy"
                    />
                  </div>
                )}
              </div>
            )
          })}
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
  // The parts breakdown is built from ALLDATA's OEM list (per labor article).
  // Real vendor prices live in the Vendor Compare step. The label below
  // honours that — saying "PartsLink24" here was a leftover lie since PL24
  // isn't even wired in for every job.
  const allFromAlldata = (data.partsItems || []).every(
    (p) => !p.vendor || /alldata/i.test(p.vendor),
  )
  const sourceLabel = allFromAlldata ? 'ALLDATA OEM list' : 'OEM list + vendor matches'
  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h2 className="text-2xl font-bold text-text-primary">Parts</h2>
        <span className="text-xs text-text-secondary">Source: {sourceLabel}</span>
      </div>

      {data.partsItems.length === 0 ? (
        <div className="bg-background p-8 rounded-lg border border-border text-center">
          <p className="text-text-secondary">No parts yet. Use Auto-Generate to populate.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.partsItems.map((part, index) => {
            const hasSavings = part.savings_vs_list != null && part.savings_vs_list > 0
            const cost = typeof part.cost === 'number' ? part.cost : parseFloat(part.cost) || 0
            return (
              <div
                key={index}
                className="bg-background p-4 rounded-lg border border-border"
              >
                <div>
                  <p className="font-semibold text-text-primary">{part.description}</p>
                  <p className="text-xs text-text-secondary mt-1">
                    OEM: <span className="font-mono">{part.partNumber || 'N/A'}</span>
                    {part.vendorSku && (
                      <>
                        {' '}• Vendor SKU: <span className="font-mono">{part.vendorSku}</span>
                      </>
                    )}
                  </p>
                  <p className="text-xs text-text-secondary">
                    Vendor: {part.vendor || 'Unknown'}
                  </p>
                  {Array.isArray(part.appliesToVariants) && part.appliesToVariants.length > 1 && (
                    <p className="text-xs text-text-secondary mt-1 italic">
                      Same SKU fits: {part.appliesToVariants.join(' · ')}
                    </p>
                  )}
                  {part.auto_added && (
                    <span className="inline-block mt-1 mr-2 px-2 py-0.5 bg-info/15 text-info text-xs rounded border border-info/30">
                      Auto-added{part.auto_added_kind ? ` (${part.auto_added_kind})` : ''}
                      {part.auto_added_reason && (
                        <span className="text-info/80 ml-1 italic">
                          — {part.auto_added_reason}
                        </span>
                      )}
                    </span>
                  )}
                  {part.isOEM && (
                    <span className="inline-block mt-1 mr-2 px-2 py-0.5 bg-accent/20 text-accent text-xs rounded">
                      OEM
                    </span>
                  )}
                  {hasSavings && (
                    <span className="inline-block mt-1 px-2 py-0.5 bg-success/15 text-success text-xs rounded border border-success/30">
                      Saved ${part.savings_vs_list.toFixed(2)} vs MSRP
                      {part.list_price != null && (
                        <span className="text-text-secondary ml-1">
                          (was ${part.list_price.toFixed(2)})
                        </span>
                      )}
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
                    <span className="text-text-secondary">${cost.toFixed(2)}</span>
                    <span className="text-text-secondary">+{part.markup}%</span>
                    <span className="text-text-secondary">=</span>
                    <span className="text-accent font-bold">${part.total}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {data.serviceSkeleton && (() => {
        const sk = data.serviceSkeleton
        const cov = sk.coverage_pct ?? 0
        const range = sk.expected_estimate_range || []
        const tier =
          cov >= 90 ? { chip: 'bg-success/15 text-success border-success/40', label: 'Full coverage' }
          : cov >= 60 ? { chip: 'bg-warning/15 text-warning border-warning/40', label: 'Partial coverage' }
          : { chip: 'bg-danger/15 text-danger border-danger/40', label: 'Missing items' }
        return (
          <div className="mt-6 bg-background p-4 rounded-lg border border-border">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div>
                <h3 className="font-semibold text-text-primary text-sm">
                  Expected components for {sk.display_name}
                </h3>
                {range.length === 2 && (
                  <p className="text-xs text-text-secondary mt-0.5">
                    Industry-standard estimate range:{' '}
                    <span className="font-mono">${range[0]}-${range[1]}</span>
                  </p>
                )}
              </div>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${tier.chip}`}>
                {tier.label} · {sk.components_found}/{sk.components_required} ({cov}%)
              </span>
            </div>
            {sk.notes && (
              <p className="text-xs text-text-secondary italic mb-3">{sk.notes}</p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {(sk.components || []).map((c, i) => (
                <div
                  key={c.key || i}
                  className={`px-3 py-2 rounded border text-xs ${
                    c.found_in_extraction
                      ? 'bg-success/5 border-success/20'
                      : c.always_required
                        ? 'bg-danger/5 border-danger/30'
                        : 'bg-surface/50 border-border/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium text-text-primary">
                      {(c.found_in_extraction || c.confirmed_by_repair_procedure)
                        ? '✓ ' : c.always_required ? '✗ ' : '○ '}
                      {c.display_name}
                      {(c.repair_procedure_qty || c.default_qty) > 1 && (
                        <span className="ml-1 text-text-secondary font-normal">
                          ×{c.repair_procedure_qty || c.default_qty}
                        </span>
                      )}
                    </p>
                    <span className="text-[10px] text-text-secondary uppercase">{c.kind}</span>
                  </div>
                  {c.reason && (
                    <p className="text-text-secondary mt-0.5 leading-snug">{c.reason}</p>
                  )}
                  {c.confirmed_by_repair_procedure && (
                    <p className="text-info mt-1 text-[11px] font-medium">
                      Confirmed by ALLDATA repair procedure ({c.repair_procedure_action})
                      {c.repair_procedure_qty && ` · qty ${c.repair_procedure_qty}`}
                    </p>
                  )}
                  {!c.found_in_extraction && !c.confirmed_by_repair_procedure && c.always_required && (
                    <p className="text-danger mt-1 text-[11px] font-medium">
                      Missing from estimate — add manually
                    </p>
                  )}
                  {c.found_in_extraction && c.matched_part_description && (
                    <p className="text-success/80 mt-0.5 text-[11px]">
                      Matched: {c.matched_part_description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })()}

      {data.repairProcedure && Array.isArray(data.repairProcedure.items)
        && data.repairProcedure.items.length > 0 && (
        <div className="mt-6 bg-background p-4 rounded-lg border border-info/40">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div>
              <h3 className="font-semibold text-text-primary text-sm">
                ALLDATA repair procedure — renew / replace items
              </h3>
              <p className="text-xs text-text-secondary mt-0.5">
                Every line the article says must be replaced, parsed for
                <span className="font-mono ml-1">renew</span> /
                <span className="font-mono ml-1">replace</span> /
                <span className="font-mono ml-1">torque-to-yield</span> keywords.
              </p>
            </div>
            <span className="text-[10px] text-text-secondary uppercase tracking-wide">
              {data.repairProcedure.items.length} items · {data.repairProcedure.raw_keyword_hits || 0} hits
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {data.repairProcedure.items.map((it, i) => {
              const actionStyle =
                it.action === 'renew' ? 'bg-warning/15 text-warning border-warning/40'
                : it.action === 'torque_to_yield' ? 'bg-danger/15 text-danger border-danger/40'
                : it.action === 'one_time_use' ? 'bg-danger/15 text-danger border-danger/40'
                : 'bg-info/15 text-info border-info/40'
              return (
                <div key={i} className="px-3 py-2 rounded border border-border/50 bg-surface/50 text-xs">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <p className="font-medium text-text-primary">
                      {it.component_phrase}
                      {it.quantity && (
                        <span className="ml-1 text-text-secondary font-normal">×{it.quantity}</span>
                      )}
                    </p>
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full border text-[10px] font-medium ${actionStyle}`}>
                      {it.action.replace(/_/g, ' ')}
                    </span>
                  </div>
                  {Array.isArray(it.contexts) && it.contexts.length > 0 && (
                    <p className="text-text-secondary italic leading-snug line-clamp-2">
                      "{it.contexts[0]}"
                    </p>
                  )}
                  {it.occurrences > 1 && (
                    <p className="text-text-secondary mt-0.5 text-[10px]">
                      Found in {it.occurrences} places in the procedure
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {data.repairProcedure && data.repairProcedure.scan_status
        && data.repairProcedure.scan_status !== 'ok'
        && data.repairProcedure.scan_status !== 'not_attempted' && (
        <div className="mt-3 px-3 py-2 rounded bg-warning/10 border border-warning/30 text-xs text-warning">
          Repair Procedure scan: {data.repairProcedure.scan_status} —
          coverage panel uses ALLDATA Parts table only
        </div>
      )}

      {Array.isArray(data.suggestedAddOns) && data.suggestedAddOns.length > 0 && (
        <div className="mt-6 bg-background p-4 rounded-lg border border-info/30">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold text-text-primary text-sm">
              Recommended add-ons
            </h3>
            <span className="text-[10px] text-text-secondary uppercase tracking-wide">
              Advisor decision · not auto-billed
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {data.suggestedAddOns.map((a, i) => (
              <div
                key={i}
                className="bg-surface/50 px-3 py-2 rounded border border-border/50"
              >
                <p className="text-sm font-medium text-text-primary">
                  {a.name}
                  {a.hours != null && (
                    <span className="ml-2 text-xs text-text-secondary font-normal">
                      ({a.hours}h)
                    </span>
                  )}
                </p>
                <p className="text-xs text-text-secondary">
                  <span className="uppercase tracking-wide mr-1 text-[10px]">{a.kind}</span>
                  · {a.reason}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}



// Push-to-Tekmetric lives on the Actions step now; PreviewStep keeps
// `onSendApproval` only.
const PreviewStep = ({ data, calculatedTotals, onSendApproval, isSending }) => {
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
          <p className="text-xs text-text-secondary mt-1">
            VIN: <span className="font-mono">{data.vin}</span>
            <span className="ml-2 text-text-secondary/70">· Decoded by NHTSA</span>
          </p>
          {data.alldataMatchedVehicle && (
            <p className="text-xs text-info mt-1">
              ALLDATA matched as: <span className="font-medium">{data.alldataMatchedVehicle}</span>
              <span className="text-text-secondary/70 ml-1">
                · labor row sourced from this catalogue entry
              </span>
            </p>
          )}
        </div>
      )}

      {data.source === 'historical' && data.historicalMatch && (
        <div className="bg-success/10 p-4 rounded-lg border border-success/40">
          <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
            <h3 className="font-semibold text-success">
              ✨ Built from your historical RO #{data.historicalMatch.roNumber}
            </h3>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-success/40 bg-success/15 text-success text-xs font-medium">
              {data.confidence?.label ||
                `Historical Match · ${Math.round((data.historicalMatch.confidence || 0) * 100)}%`}
            </span>
          </div>
          <p className="text-xs text-text-secondary">
            Matched from {data.historicalMatch.matchedVehicle}
            {data.historicalMatch.datePosted ? ` · posted ${data.historicalMatch.datePosted}` : ''}.
            {' '}Labor &amp; parts come from this shop's own past paid estimate —
            prices may need a live refresh.
          </p>
          {data.historicalMatch.filtered && (
            <p className="text-[10px] text-warning/90 mt-1">
              Filtered to the labor &amp; parts relevant to this request — RO #{data.historicalMatch.roNumber} also
              included other work from that visit, which has been left out.
            </p>
          )}
          {!data.historicalMatch.filtered && data.historicalMatch.services && (
            <p className="text-[10px] text-text-secondary/70 mt-1 truncate">
              Services: {data.historicalMatch.services}
            </p>
          )}
        </div>
      )}

      {Array.isArray(data.recalls) && data.recalls.length > 0 && (
        <div className="bg-background p-4 rounded-lg border border-warning/40">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold text-warning">
              {data.recalls.length} active NHTSA recall{data.recalls.length === 1 ? '' : 's'}
            </h3>
            <span className="text-[10px] text-text-secondary uppercase tracking-wide">
              Informational · not auto-billed
            </span>
          </div>
          <ul className="space-y-2">
            {data.recalls.slice(0, 5).map((rc, i) => (
              <li key={i} className="text-xs text-text-secondary border-l-2 border-warning/40 pl-2">
                <p className="font-medium text-text-primary">
                  {rc.component || 'Recall'}
                  {rc.campaign_number && (
                    <span className="font-mono text-text-secondary ml-2">
                      {rc.campaign_number}
                    </span>
                  )}
                </p>
                {rc.summary && <p className="mt-0.5 line-clamp-2">{rc.summary}</p>}
              </li>
            ))}
            {data.recalls.length > 5 && (
              <li className="text-xs text-text-secondary italic">
                + {data.recalls.length - 5} more — full list on NHTSA
              </li>
            )}
          </ul>
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

      {/* Preview is read-only on purpose. The "Push to Tekmetric" CTA used
          to live here too, which led advisors to push and *then* discover
          they hadn't reviewed the Vendor Compare or Actions tabs yet, with
          some pushing twice. The canonical push button is now on the
          Actions step alongside the rest of the finish-and-send controls.
          We keep "Send Approval Link" here because customer approval is a
          distinct intent that benefits from being one click away after the
          advisor has eyeballed the totals on this page. */}
      <div className="flex flex-col sm:flex-row items-center gap-4">
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
        <p className="text-xs text-text-secondary">
          Tip: review Vendor Compare next, then push to Tekmetric from the Actions tab.
        </p>
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
    // Persist the active job + intake so a page refresh can RESUME polling or
    // restore the finished result instead of dropping a 10-minute job on the
    // floor (the backend keeps the result; only the FE was forgetting it).
    const intakeSnapshot = {
      vin: formData.vin,
      serviceRequest: formData.serviceRequest,
      customerName: formData.customerName,
      customerEmail: formData.customerEmail,
      customerPhone: formData.customerPhone,
      odometer: formData.odometer,
    }
    try {
      localStorage.setItem('estimaro_active_job',
        JSON.stringify({ jobId, intake: intakeSnapshot }))
    } catch { /* storage full/blocked — resume just won't work */ }
    setAgentProgress({
      jobId,
      status: submit.data.status,
      progress: submit.data.progress,
      progress_pct: submit.data.progress_pct,
    })

    // 2. Poll until terminal. 25 min — a fresh ALLDATA run + vendor agents can
    // exceed the old 10-min cap (observed 12 min), which left the progress
    // card stuck on RUNNING while the job actually completed.
    const poll = await pollAutoGenJob(jobId, {
      intervalMs: 2500,
      timeoutMs: 1500000,
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
    try { localStorage.removeItem('estimaro_active_job') } catch { /* noop */ }

    if (job.status === 'failed') {
      toast.error(job.error || 'Agent failed to complete the estimate', 'Generation Failed')
      setIsGenerating(false)
      setAgentProgress(null)
      return
    }

    await applyJobResult(job, intakeSnapshot)
  }

  // Populate all estimate state from a completed auto-gen job. Shared by the
  // live submit path and the refresh-recovery path (restoring a job whose
  // result the backend held while the page was reloaded).
  const applyJobResult = async (job, intake) => {
    const iv = intake || formData
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
      // Base64 data URL of the source ALLDATA page. Null on older workers
      // or when the file was missing — LaborStep hides the "View source"
      // toggle in that case so the UI doesn't show a broken control.
      extractionScreenshot: item.extractionScreenshot || null,
      // Task #15 — determinism signal. Tells the FE whether the picked
      // labor row is the canonical (preferred) one for the service
      // type, a fallback that's still on-list, or off-script.
      determinism_status: item.determinism_status ?? null,
      determinism_rank: item.determinism_rank ?? null,
      determinism_preferred: item.determinism_preferred ?? null,
      // Task #14 — labor addons (e.g. Wheel Alignment for suspension).
      auto_added: !!item.auto_added,
      auto_added_reason: item.auto_added_reason ?? null,
    }))
    const partsItems = (r.partsItems || []).map((item, idx) => ({
      id: idx + 1,
      description: item.description,
      partNumber: item.partNumber,
      // Vendor's own SKU when it differs from the OEM number — the worker
      // omits this field when they match, so a falsy check is correct here.
      vendorSku: item.vendorSku ?? null,
      // Wheel-size / option variants ALLDATA listed under the same OEM that
      // the worker collapsed into this single line. UI uses it to disclose
      // "Same SKU fits: 15\" Wheels · 16\" Wheels" instead of silently
      // hiding the dedup.
      appliesToVariants: Array.isArray(item.appliesToVariants)
        ? item.appliesToVariants
        : null,
      quantity: item.quantity,
      cost: item.cost,
      markup: item.markup,
      total: parseFloat(item.total).toFixed(2),
      vendor: item.vendor || 'ALLDATA',
      // Passed through when the worker substituted a vendor quote for
      // ALLDATA's MSRP — PartsStep renders a "Saved $X vs MSRP" badge.
      list_price: item.list_price ?? null,
      savings_vs_list: item.savings_vs_list ?? null,
      // Task #14 — skeleton addon auto-add flags (cleaning kit, multi-
      // point inspection, etc.). PartsStep shows an "Auto-added per
      // service type" badge so the advisor knows the line wasn't from
      // ALLDATA extraction or a vendor quote.
      auto_added: !!item.auto_added,
      auto_added_kind: item.auto_added_kind ?? null,
      auto_added_reason: item.auto_added_reason ?? null,
    }))

    // ALLDATA's banner shows a more specific trim than NHTSA usually does
    // (V70 → XC70 L5-2.4L Turbo). Pass it through so PreviewStep can show
    // "ALLDATA matched as: ..." beneath the NHTSA-decoded line, instead of
    // the advisor having to wonder which catalogue the labor came from.
    const alldataMatchedVehicle = r.alldataMatchedVehicle ?? null
    // Aux data: NHTSA recalls (banner) and recommended add-ons (panel).
    const recalls = Array.isArray(r.recalls) ? r.recalls : []
    const suggestedAddOns = Array.isArray(r.suggestedAddOns) ? r.suggestedAddOns : []
    // Task #12 — service-type skeleton + coverage. Null when worker didn't
    // recognise the service type; FE hides the panel in that case.
    const serviceSkeleton = r.serviceSkeleton || null
    // Task #13 — Repair-Procedure scan items. Surfaced separately so the
    // FE can show the raw renew/replace list even when no skeleton was
    // matched, and so the advisor sees ALLDATA's exact procedure-language
    // hits (with the context phrase) rather than just the merged coverage.
    const repairProcedure = r.repairProcedure || null
    // Phase C/D — historical RO match metadata, for the "Built from your
    // RO #X" banner. Null on the normal live-build path.
    const source = r.source || null
    const historicalMatch = r.historicalMatch || null
    const confidence = r.confidence || null

    const mergedData = {
      vin: iv.vin,
      serviceRequest: iv.serviceRequest,
      customerName: iv.customerName,
      customerEmail: iv.customerEmail,
      customerPhone: iv.customerPhone,
      odometer: iv.odometer,
      vehicleInfo: veh,
      alldataMatchedVehicle,
      laborItems,
      partsItems,
      recalls,
      suggestedAddOns,
      serviceSkeleton,
      repairProcedure,
      source,
      historicalMatch,
      confidence,
    }

    setFormData((prev) => ({
      ...prev,
      // Re-assert the intake fields too: on the refresh-recovery path the
      // form state starts empty, so the result must bring its intake along.
      vin: iv.vin ?? prev.vin,
      serviceRequest: iv.serviceRequest ?? prev.serviceRequest,
      customerName: iv.customerName ?? prev.customerName,
      customerEmail: iv.customerEmail ?? prev.customerEmail,
      customerPhone: iv.customerPhone ?? prev.customerPhone,
      odometer: iv.odometer ?? prev.odometer,
      vehicleInfo: veh,
      alldataMatchedVehicle,
      laborItems,
      partsItems,
      recalls,
      suggestedAddOns,
      serviceSkeleton,
      repairProcedure,
      source,
      historicalMatch,
      confidence,
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
      // Layer 6 — worker-computed tier + aggregate score. UI shows
      // these directly; do NOT recompute from extraction/verification on
      // the FE or the gating policy will drift across versions.
      overall: r.confidence ?? null,
      // Layer 5 — per-part vendor consensus. Used to drive the
      // "Sources: X/Y vendors" sub-chip and any per-row outlier badges.
      consensus: r.consensus ?? null,
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
    const today = new Date()
    const validUntil = new Date(today.getTime() + 30 * 24 * 60 * 60 * 1000)
    const fmtDate = (d) => d.toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    })
    const estimateNumber = `EST-${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}-${String(today.getHours()).padStart(2, '0')}${String(today.getMinutes()).padStart(2, '0')}`

    // ---- Letterhead band ----
    doc.setFillColor(15, 30, 50)
    doc.rect(0, 0, 210, 28, 'F')
    doc.setTextColor(255, 255, 255)
    doc.setFontSize(18)
    doc.setFont(undefined, 'bold')
    doc.text('GERMAN SPORT AUTO REPAIR', 14, 14)
    doc.setFont(undefined, 'normal')
    doc.setFontSize(9)
    doc.text('Service · Estimation · Vehicle Diagnostics', 14, 20)
    doc.setFontSize(8)
    doc.text('Auto-generated by Estimaro · Powered by ALLDATA + verified vendor catalogues', 14, 25)

    // ---- Meta block (right-aligned) ----
    doc.setTextColor(40, 40, 40)
    doc.setFontSize(16)
    doc.setFont(undefined, 'bold')
    doc.text('ESTIMATE', 196, 38, { align: 'right' })
    doc.setFontSize(9)
    doc.setFont(undefined, 'normal')
    doc.text(`# ${estimateNumber}`, 196, 44, { align: 'right' })
    doc.text(`Issued: ${fmtDate(today)}`, 196, 49, { align: 'right' })
    doc.text(`Valid until: ${fmtDate(validUntil)}`, 196, 54, { align: 'right' })

    // ---- Customer + Vehicle two-column ----
    doc.setDrawColor(220, 220, 220)
    doc.line(14, 38, 130, 38)
    doc.setFontSize(9)
    doc.setTextColor(120, 120, 120)
    doc.text('PREPARED FOR', 14, 44)
    doc.setTextColor(40, 40, 40)
    doc.setFontSize(11)
    doc.setFont(undefined, 'bold')
    doc.text(formData.customerName || '—', 14, 51)
    doc.setFont(undefined, 'normal')
    doc.setFontSize(9)
    doc.setTextColor(80, 80, 80)
    if (formData.customerEmail) doc.text(formData.customerEmail, 14, 57)
    doc.text(formData.customerPhone || '', 14, formData.customerEmail ? 62 : 57)

    if (formData.vehicleInfo) {
      doc.setFontSize(9)
      doc.setTextColor(120, 120, 120)
      doc.text('VEHICLE', 72, 44)
      doc.setTextColor(40, 40, 40)
      doc.setFontSize(11)
      doc.setFont(undefined, 'bold')
      doc.text(`${formData.vehicleInfo.year || ''} ${formData.vehicleInfo.make || ''} ${formData.vehicleInfo.model || ''}`.trim(), 72, 51)
      doc.setFont(undefined, 'normal')
      doc.setFontSize(9)
      doc.setTextColor(80, 80, 80)
      doc.text(`VIN: ${formData.vin || '—'}`, 72, 57)
      if (formData.odometer) doc.text(`Odometer: ${formData.odometer}`, 72, 62)
      if (formData.alldataMatchedVehicle && formData.alldataMatchedVehicle !==
        `${formData.vehicleInfo.year} ${formData.vehicleInfo.make} ${formData.vehicleInfo.model}`) {
        doc.setTextColor(120, 120, 120)
        doc.setFontSize(8)
        doc.text(`Catalogue match: ${formData.alldataMatchedVehicle}`, 72, formData.odometer ? 67 : 62)
      }
    }

    // ---- Service request ----
    doc.setDrawColor(220, 220, 220)
    doc.line(14, 76, 196, 76)
    doc.setFontSize(9)
    doc.setTextColor(120, 120, 120)
    doc.text('SERVICE REQUEST', 14, 82)
    doc.setFontSize(10)
    doc.setTextColor(40, 40, 40)
    doc.text(formData.serviceRequest || '—', 14, 88, { maxWidth: 180 })

    let currentY = 100

    // ---- Labor table ----
    if (formData.laborItems.length > 0) {
      autoTable(doc, {
        startY: currentY,
        head: [['Labor', 'Skill', 'Hours', 'Rate', 'Total']],
        body: formData.laborItems.map(item => [
          item.description,
          item.skill || '—',
          `${item.hours}h`,
          `$${item.rate}/hr`,
          `$${item.total}`,
        ]),
        theme: 'striped',
        headStyles: { fillColor: [15, 30, 50], textColor: [255, 255, 255], fontSize: 9 },
        bodyStyles: { fontSize: 9 },
        columnStyles: {
          2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' },
        },
      })
      currentY = doc.lastAutoTable.finalY + 8
    }

    // ---- Parts table (expanded: OEM + Vendor SKU columns) ----
    if (formData.partsItems.length > 0) {
      autoTable(doc, {
        startY: currentY,
        head: [['Part', 'OEM #', 'Vendor SKU', 'Vendor', 'Qty', 'Unit', 'Total']],
        body: formData.partsItems.map(item => [
          item.description,
          item.partNumber || '—',
          item.vendorSku || '—',
          item.vendor || '—',
          item.quantity,
          `$${item.cost}`,
          `$${item.total}`,
        ]),
        theme: 'striped',
        headStyles: { fillColor: [15, 30, 50], textColor: [255, 255, 255], fontSize: 9 },
        bodyStyles: { fontSize: 8 },
        columnStyles: {
          4: { halign: 'right' }, 5: { halign: 'right' }, 6: { halign: 'right' },
        },
      })
      currentY = doc.lastAutoTable.finalY + 10
    }

    // ---- Totals box (right-aligned) ----
    const totalsX = 130
    doc.setFontSize(10)
    doc.setTextColor(80, 80, 80)
    doc.text(`Labor Total`, totalsX, currentY)
    doc.text(`$${calculatedTotals.laborTotal}`, 196, currentY, { align: 'right' })
    doc.text(`Parts Total`, totalsX, currentY + 6)
    doc.text(`$${calculatedTotals.partsTotal}`, 196, currentY + 6, { align: 'right' })
    doc.text(`Subtotal`, totalsX, currentY + 12)
    doc.text(`$${calculatedTotals.subtotal}`, 196, currentY + 12, { align: 'right' })
    doc.text(`Tax (${(formData.taxRate * 100).toFixed(1)}%)`, totalsX, currentY + 18)
    doc.text(`$${calculatedTotals.taxAmount}`, 196, currentY + 18, { align: 'right' })
    doc.setDrawColor(180, 180, 180)
    doc.line(totalsX, currentY + 22, 196, currentY + 22)
    doc.setFontSize(13)
    doc.setFont(undefined, 'bold')
    doc.setTextColor(15, 30, 50)
    doc.text(`TOTAL`, totalsX, currentY + 30)
    doc.text(`$${calculatedTotals.total}`, 196, currentY + 30, { align: 'right' })
    doc.setFont(undefined, 'normal')

    // ---- Recalls page ----
    if (Array.isArray(formData.recalls) && formData.recalls.length > 0) {
      doc.addPage()
      doc.setFontSize(14)
      doc.setTextColor(40, 40, 40)
      doc.setFont(undefined, 'bold')
      doc.text('Active NHTSA Recalls', 14, 20)
      doc.setFont(undefined, 'normal')
      doc.setFontSize(9)
      doc.setTextColor(120, 120, 120)
      doc.text(
        'Informational only. Recalls below are open as of estimate date and are not included in this estimate\'s totals.',
        14, 26, { maxWidth: 182 },
      )
      autoTable(doc, {
        startY: 34,
        head: [['Campaign #', 'Component', 'Summary']],
        body: formData.recalls.map(rc => [
          rc.campaign_number || '—',
          rc.component || '—',
          rc.summary || '—',
        ]),
        theme: 'striped',
        headStyles: { fillColor: [180, 100, 40], textColor: [255, 255, 255], fontSize: 9 },
        bodyStyles: { fontSize: 8 },
        columnStyles: { 0: { cellWidth: 30 }, 1: { cellWidth: 45 } },
      })
    }

    // ---- Footer (every page) ----
    const pageCount = doc.internal.getNumberOfPages()
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i)
      doc.setFontSize(8)
      doc.setTextColor(150, 150, 150)
      doc.text(
        `This estimate is valid until ${fmtDate(validUntil)}. Prices subject to vendor availability. Generated by Estimaro.`,
        105, 286, { align: 'center', maxWidth: 180 },
      )
      doc.text(`Page ${i} of ${pageCount}`, 196, 292, { align: 'right' })
    }

    // ---- Save ----
    doc.save(`Estimate_${(formData.customerName || 'customer').replace(/\s+/g, '_')}_${today.toISOString().split('T')[0]}.pdf`)
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

  // Refresh recovery — if a generation job was in flight (or finished) when
  // the page reloaded, pick it back up from localStorage instead of showing
  // an empty form while the backend silently holds a completed estimate.
  useEffect(() => {
    let saved
    try { saved = localStorage.getItem('estimaro_active_job') } catch { return }
    if (!saved) return
    let parsed
    try { parsed = JSON.parse(saved) } catch {
      try { localStorage.removeItem('estimaro_active_job') } catch { /* noop */ }
      return
    }
    const { jobId, intake } = parsed || {}
    if (!jobId) return
    ;(async () => {
      const first = await getAutoGenJob(jobId)
      if (!first.success) return // backend unreachable — leave the key for next load
      const job = first.data
      if (job.status === 'failed') {
        try { localStorage.removeItem('estimaro_active_job') } catch { /* noop */ }
        toast.error(job.error || 'Your last generation failed', 'Previous job')
        return
      }
      if (job.status === 'success') {
        try { localStorage.removeItem('estimaro_active_job') } catch { /* noop */ }
        await applyJobResult(job, intake)
        toast.success('Recovered your completed estimate from the last session', 'Restored')
        return
      }
      // Still running — restore the intake form and resume polling.
      if (intake) setFormData((prev) => ({ ...prev, ...intake }))
      setIsGenerating(true)
      setAgentProgress({ jobId, status: job.status, progress: job.progress,
                         progress_pct: job.progress_pct })
      const poll = await pollAutoGenJob(jobId, {
        intervalMs: 2500,
        timeoutMs: 1500000,
        onProgress: (j) => setAgentProgress({
          jobId: j.job_id, status: j.status,
          progress: j.progress, progress_pct: j.progress_pct,
        }),
      })
      try { localStorage.removeItem('estimaro_active_job') } catch { /* noop */ }
      if (poll.success && poll.data.status === 'success') {
        await applyJobResult(poll.data, intake)
      } else {
        setIsGenerating(false)
        setAgentProgress(null)
        toast.error(
          poll.success ? (poll.data.error || 'Generation failed') : (poll.error || 'Polling failed'),
          'Previous job',
        )
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
          onSendApproval={handleSendApproval}
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

      {/* Confidence chip — Layer 6 of the proposal. Worker decides tier
          (auto / advisor_review / manual_review); we just render. Hover
          surfaces the breakdown so the advisor can see which sub-score
          dragged the verdict down (extraction vs verification vs sourcing). */}
      {confidenceScore && !isGenerating && (formData.laborItems.length > 0 || formData.partsItems.length > 0) && (() => {
        const overall = confidenceScore.overall
        const tier = overall?.tier
        const score = overall?.score
        // Tier → visual style + human label. Mapping mirrors the proposal:
        // ≥0.90 auto, 0.70-0.89 spot-check, <0.70 manual.
        const tierStyle = tier === 'auto'
          ? { dot: 'bg-success', label: 'Auto-approve', ring: 'border-success/40' }
          : tier === 'advisor_review'
          ? { dot: 'bg-warning', label: 'Advisor review', ring: 'border-warning/40' }
          : tier === 'manual_review'
          ? { dot: 'bg-danger', label: 'Manual review', ring: 'border-danger/40' }
          // Old worker (no Layer 6 yet) → fall back to the original
          // verification-only signal so a partial rollout still shows
          // *something* useful instead of "—".
          : {
              dot: (confidenceScore.verification_confidence ?? 0) >= 0.9 ? 'bg-success'
                : (confidenceScore.verification_confidence ?? 0) >= 0.7 ? 'bg-warning' : 'bg-danger',
              label: confidenceScore.verification_match ? 'Verified' : 'Unverified',
              ring: 'border-border',
            }
        const pct = score != null
          ? Math.round(score * 100)
          : (confidenceScore.verification_confidence != null
              ? Math.round(confidenceScore.verification_confidence * 100)
              : null)
        // Sources sub-chip — picks the WORST coverage across all consensus
        // groups so a partial single-source group drags the chip down even
        // when other parts had multi-source agreement. Hidden when consensus
        // wasn't returned (e.g. all maintenance, no vendor lookups).
        const consensusGroups = confidenceScore.consensus ? Object.values(confidenceScore.consensus) : []
        let sourcesChip = null
        if (consensusGroups.length > 0) {
          const worst = consensusGroups.reduce((acc, g) => {
            const total = g.vendors_total || 0
            const priced = g.vendors_with_price || 0
            if (acc == null || priced < acc.priced) return { priced, total, outliers: (g.outliers || []).length }
            return acc
          }, null)
          if (worst) {
            const sStyle = worst.priced >= 2 && worst.outliers === 0 ? 'bg-success/15 text-success border-success/30'
              : worst.priced >= 2 ? 'bg-warning/15 text-warning border-warning/30'
              : worst.priced === 1 ? 'bg-warning/15 text-warning border-warning/30'
              : 'bg-danger/15 text-danger border-danger/30'
            sourcesChip = (
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-medium ${sStyle}`}
                    title={worst.outliers > 0 ? `${worst.outliers} vendor outlier(s) vs median price` : 'Vendor agreement on price'}>
                Sources: {worst.priced}/{worst.total}
                {worst.outliers > 0 ? ` · ${worst.outliers} outlier` : ''}
              </span>
            )
          }
        }
        const tooltip = [
          overall?.breakdown && `Extraction ${Math.round((overall.breakdown.extraction || 0) * 100)}% · Verification ${Math.round((overall.breakdown.verification || 0) * 100)}% · Sourcing ${Math.round((overall.breakdown.sourcing || 0) * 100)}%`,
          overall?.breakdown?.sourcing_note && `Sourcing: ${overall.breakdown.sourcing_note.replace(/_/g, ' ')}`,
          confidenceScore.section_path && `Path: ${confidenceScore.section_path}`,
          confidenceScore.verification_reason && `Hermes: ${confidenceScore.verification_reason}`,
          confidenceScore.agent_steps != null && `${confidenceScore.agent_steps} agent steps`,
          confidenceScore.elapsed_sec != null && `${confidenceScore.elapsed_sec.toFixed(1)}s elapsed`,
        ].filter(Boolean).join(' · ')
        return (
          <div className="w-full max-w-4xl mx-auto mb-4 flex justify-end items-center gap-2">
            {sourcesChip}
            <div
              className={`group relative inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface border ${tierStyle.ring} text-xs text-text-secondary cursor-help`}
              title={tooltip}
            >
              <span className={`inline-block h-2 w-2 rounded-full ${tierStyle.dot}`} />
              <span>
                {tierStyle.label}
                {pct != null ? ` · ${pct}%` : ''}
              </span>
            </div>
          </div>
        )
      })()}

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
