import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { CheckCircleIcon, XCircleIcon, PhoneIcon, DocumentTextIcon, BanknotesIcon } from '@heroicons/react/24/outline'
import { processApprovalAction } from '../services/api'
import axios from 'axios'

// Direct API call for viewing estimate (since it's a public endpoint not in main api.js wrapper properly for GET with params in URL path for this specific case matching the backend route)
// Actually I added view_estimate in backend but didn't add it explicitely in api.js as a named export for view (I added generate and process).
// Let's use axios directly or add it to api.js? I'll use axios directly for this public route to be safe or just fetch.
// Wait, the backend route is /api/v1/approval/view/{token}

const CustomerApproval = () => {
    const { token } = useParams()
    const [estimate, setEstimate] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [actionStatus, setActionStatus] = useState(null) // 'processing', 'success', 'error'
    const [notes, setNotes] = useState('')

    useEffect(() => {
        const fetchEstimate = async () => {
            try {
                // Using direct axios call to ensure we hit the public endpoint correctly
                const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'
                const response = await axios.get(`${API_URL}/approval/view/${token}`)

                if (response.data.success) {
                    setEstimate(response.data)
                } else {
                    setError(response.data.error || 'Failed to load estimate')
                }
            } catch (err) {
                setError(err.response?.data?.detail || 'Invalid or expired estimate link')
            } finally {
                setLoading(false)
            }
        }

        if (token) {
            fetchEstimate()
        }
    }, [token])

    const handleAction = async (action) => {
        if (!confirm(`Are you sure you want to ${action} this estimate?`)) return

        setActionStatus('processing')

        try {
            const result = await processApprovalAction(token, action, notes)

            if (result.success) {
                setActionStatus('success')
                // Update local state to reflect change
                setEstimate(prev => ({
                    ...prev,
                    status: result.data.status
                }))
            } else {
                alert(result.error)
                setActionStatus('error')
            }
        } catch (err) {
            alert('Action failed. Please try again.')
            setActionStatus('error')
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen bg-background flex items-center justify-center">
                <div className="animate-spin h-12 w-12 border-4 border-accent border-t-transparent rounded-full"></div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="min-h-screen bg-background flex items-center justify-center p-4">
                <div className="bg-surface p-8 rounded-xl shadow-2xl max-w-md w-full text-center border border-danger/20">
                    <XCircleIcon className="h-16 w-16 text-danger mx-auto mb-4" />
                    <h2 className="text-2xl font-bold text-text-primary mb-2">Unavailable</h2>
                    <p className="text-text-secondary">{error}</p>
                </div>
            </div>
        )
    }

    if (!estimate) return null

    const { estimate_data, status } = estimate
    const { vehicleInfo, breakdown, customer } = estimate_data
    const isPending = status === 'pending'
    const isApproved = status === 'approved'
    const isDeclined = status === 'declined'

    return (
        <div className="min-h-screen bg-background py-8 px-4 sm:px-6 lg:px-8">
            <div className="max-w-3xl mx-auto space-y-8">

                {/* Header */}
                <div className="text-center space-y-2">
                    <h1 className="text-3xl font-bold text-text-primary">Estimate Approval</h1>
                    <p className="text-text-secondary">Please review the details below</p>
                </div>

                {/* Status Banner */}
                {!isPending && (
                    <div className={`p-6 rounded-xl border flex items-center justify-center gap-3 ${isApproved ? 'bg-success/10 border-success/30 text-success' :
                            isDeclined ? 'bg-danger/10 border-danger/30 text-danger' :
                                'bg-warning/10 border-warning/30 text-warning'
                        }`}>
                        {isApproved && <CheckCircleIcon className="h-8 w-8" />}
                        {isDeclined && <XCircleIcon className="h-8 w-8" />}
                        <span className="text-lg font-bold uppercase tracking-wide">
                            {status.replace('_', ' ')}
                        </span>
                    </div>
                )}

                {/* Vehicle & Customer Card */}
                <div className="bg-surface rounded-xl shadow-lg border border-border overflow-hidden">
                    <div className="bg-primary/5 p-4 border-b border-border flex justify-between items-center">
                        <h3 className="font-semibold text-text-primary flex items-center gap-2">
                            <DocumentTextIcon className="h-5 w-5 text-accent" />
                            Estimate Details
                        </h3>
                        <span className="text-sm text-text-secondary">
                            ID: {estimate.estimate_id}
                        </span>
                    </div>
                    <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <p className="text-sm text-text-secondary uppercase tracking-wider mb-1">Vehicle</p>
                            <p className="font-bold text-lg text-text-primary">
                                {vehicleInfo.year} {vehicleInfo.make} {vehicleInfo.model}
                            </p>
                            <p className="text-text-secondary">{vehicleInfo.trim}</p>
                            <p className="text-xs text-text-secondary mt-1 font-mono">VIN: {vehicleInfo.vin}</p>
                        </div>
                        <div>
                            <p className="text-sm text-text-secondary uppercase tracking-wider mb-1">Customer</p>
                            <p className="font-bold text-lg text-text-primary">{customer.name}</p>
                            <p className="text-text-secondary">{customer.phone}</p>
                            <p className="text-text-secondary">{customer.email}</p>
                        </div>
                    </div>
                </div>

                {/* Cost Breakdown */}
                <div className="bg-surface rounded-xl shadow-lg border border-border overflow-hidden">
                    <div className="bg-primary/5 p-4 border-b border-border">
                        <h3 className="font-semibold text-text-primary flex items-center gap-2">
                            <BanknotesIcon className="h-5 w-5 text-accent" />
                            Cost Summary
                        </h3>
                    </div>
                    <div className="p-6 space-y-3">
                        <div className="flex justify-between text-text-secondary">
                            <span>Labor Total</span>
                            <span>${breakdown.laborTotal}</span>
                        </div>
                        <div className="flex justify-between text-text-secondary">
                            <span>Parts Total</span>
                            <span>${breakdown.partsTotal}</span>
                        </div>
                        {breakdown.cleaningKit && (
                            <div className="flex justify-between text-text-secondary">
                                <span>{breakdown.cleaningKit.name}</span>
                                <span>${breakdown.cleaningKit.price}</span>
                            </div>
                        )}
                        <div className="flex justify-between text-text-secondary">
                            <span>Tax</span>
                            <span>${breakdown.taxAmount}</span>
                        </div>
                        <div className="pt-4 mt-2 border-t border-border flex justify-between items-center">
                            <span className="text-xl font-bold text-text-primary">Total Amount</span>
                            <span className="text-2xl font-bold text-accent">${breakdown.total}</span>
                        </div>
                    </div>
                </div>

                {/* Action Buttons (Only if Pending) */}
                {isPending && (
                    <div className="space-y-4">
                        <div className="bg-surface p-4 rounded-xl border border-border">
                            <label className="block text-sm font-medium text-text-secondary mb-2">
                                Notes / Questions (Optional)
                            </label>
                            <textarea
                                value={notes}
                                onChange={(e) => setNotes(e.target.value)}
                                placeholder="Any special instructions or questions?"
                                className="w-full bg-background border border-border rounded-lg p-3 text-text-primary focus:ring-2 focus:ring-accent outline-none"
                                rows="3"
                            />
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <button
                                onClick={() => handleAction('approve')}
                                disabled={actionStatus === 'processing'}
                                className="bg-success hover:bg-success-dark text-background font-bold py-4 px-6 rounded-xl shadow-lg shadow-success/20 transition-all transform hover:scale-105 flex items-center justify-center gap-2"
                            >
                                <CheckCircleIcon className="h-6 w-6" />
                                Approve Estimate
                            </button>

                            <button
                                onClick={() => handleAction('decline')}
                                disabled={actionStatus === 'processing'}
                                className="bg-surface hover:bg-danger/10 border border-border text-text-secondary hover:text-danger font-bold py-4 px-6 rounded-xl transition-all flex items-center justify-center gap-2"
                            >
                                <XCircleIcon className="h-6 w-6" />
                                Decline
                            </button>
                        </div>

                        <div className="text-center">
                            <button
                                onClick={() => handleAction('callback')}
                                disabled={actionStatus === 'processing'}
                                className="text-accent hover:text-accent-dark font-medium text-sm flex items-center justify-center gap-1 mx-auto"
                            >
                                <PhoneIcon className="h-4 w-4" />
                                Request a call back from advisor
                            </button>
                        </div>
                    </div>
                )}

                {/* Footer */}
                <div className="text-center text-text-secondary text-sm pt-8 pb-4">
                    <p>Powered by Estimaro • {new Date().getFullYear()}</p>
                </div>

            </div>
        </div>
    )
}

export default CustomerApproval
