// src/components/Settings.jsx
// Real persistence via /api/v1/settings/. Secrets come back masked from the
// backend — re-saving without editing them leaves the stored value alone.

import React, { useEffect, useState } from 'react'
import { Mail, Smartphone, X } from 'lucide-react'
import { ArrowPathIcon } from '@heroicons/react/24/outline'
import { getShopSettings, updateShopSettings } from '../services/api'
import { useToast } from './ui/Toast'

const SettingsPage = () => {
  const toast = useToast()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const [shopName, setShopName] = useState('')
  const [laborRate, setLaborRate] = useState(150)
  const [partsMarkup, setPartsMarkup] = useState(30)
  const [tax, setTax] = useState(9.25)
  const [brandWeight, setBrandWeight] = useState(40)
  const [priceWeight, setPriceWeight] = useState(35)
  const [distanceWeight, setDistanceWeight] = useState(25)
  const [advisors, setAdvisors] = useState([])
  const [newAdvisor, setNewAdvisor] = useState('')
  const [emailTemplate, setEmailTemplate] = useState('')
  const [smsTemplate, setSmsTemplate] = useState('')

  const [tekmetricApiKey, setTekmetricApiKey] = useState('')
  const [tekmetricShopId, setTekmetricShopId] = useState('')
  const [alldataCredentials, setAlldataCredentials] = useState('')
  const [partsLinkToken, setPartsLinkToken] = useState('')

  const [twilioSid, setTwilioSid] = useState('')
  const [twilioToken, setTwilioToken] = useState('')
  const [twilioPhone, setTwilioPhone] = useState('')

  const hydrate = (data) => {
    // shop_name may carry the Vendors page's brand-preference suffix
    // (|brands:...) — strip it for display so users edit the clean name.
    setShopName((data.shop_name || '').split('|brands:')[0])
    setLaborRate(data.shop?.labor_rate ?? 150)
    setPartsMarkup(data.shop?.parts_markup ?? 30)
    setTax(data.shop?.tax_rate ?? 9.25)
    setBrandWeight(data.scoring?.brand ?? 40)
    setPriceWeight(data.scoring?.price ?? 35)
    setDistanceWeight(data.scoring?.distance ?? 25)
    setAdvisors(Array.isArray(data.advisors) ? data.advisors : [])
    setEmailTemplate(data.templates?.email ?? '')
    setSmsTemplate(data.templates?.sms ?? '')
    setTekmetricApiKey(data.integrations?.tekmetric?.api_key ?? '')
    setTekmetricShopId(data.integrations?.tekmetric?.shop_id ?? '')
    setAlldataCredentials(data.integrations?.external?.alldata ?? '')
    setPartsLinkToken(data.integrations?.external?.partslink24_token ?? '')
    setTwilioSid(data.integrations?.twilio?.sid ?? '')
    setTwilioToken(data.integrations?.twilio?.auth_token ?? '')
    setTwilioPhone(data.integrations?.twilio?.phone ?? '')
  }

  const load = async () => {
    setLoading(true)
    setError(null)
    const r = await getShopSettings()
    if (r.success) hydrate(r.data)
    else setError(r.error)
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  const addAdvisor = () => {
    const name = newAdvisor.trim()
    if (!name || advisors.includes(name)) return
    setAdvisors([...advisors, name])
    setNewAdvisor('')
  }

  const removeAdvisor = (name) => {
    setAdvisors(advisors.filter((a) => a !== name))
  }

  const handleSave = async () => {
    setSaving(true)
    // Preserve the brand-preference suffix the Vendors page may have appended.
    const r0 = await getShopSettings()
    const brandSuffix = r0.success
      ? (r0.data.shop_name || '').match(/(\|brands:.*)$/)?.[1] || ''
      : ''
    const payload = {
      shop_name: `${shopName.trim()}${brandSuffix}`,
      shop: {
        labor_rate: Number(laborRate),
        parts_markup: Number(partsMarkup),
        tax_rate: Number(tax),
      },
      scoring: {
        brand: Number(brandWeight),
        price: Number(priceWeight),
        distance: Number(distanceWeight),
      },
      advisors,
      templates: { email: emailTemplate, sms: smsTemplate },
      integrations: {
        tekmetric: { api_key: tekmetricApiKey, shop_id: tekmetricShopId },
        twilio: { sid: twilioSid, auth_token: twilioToken, phone: twilioPhone },
        external: { alldata: alldataCredentials, partslink24_token: partsLinkToken },
      },
    }
    const r = await updateShopSettings(payload)
    if (r.success) {
      hydrate(r.data) // refresh with the new masked secrets
      toast.success('Settings saved', 'Done')
    } else {
      toast.error(r.error, 'Save failed')
    }
    setSaving(false)
  }

  if (loading) {
    return (
      <div className="min-h-screen p-4 sm:p-8 bg-background text-text-primary">
        <div className="max-w-4xl mx-auto space-y-6">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-2xl bg-surface border border-border animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen p-4 sm:p-8 bg-background text-text-primary font-inter">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl md:text-3xl font-bold text-text-primary">Settings</h1>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary bg-surface hover:bg-primary/20 border border-border rounded-lg transition-colors disabled:opacity-50"
            >
              <ArrowPathIcon className="h-4 w-4" />
              Reload
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 bg-accent text-background font-bold rounded-lg hover:bg-accent/80 shadow disabled:opacity-60 transition-colors"
            >
              {saving ? 'Saving…' : 'Save All'}
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-surface p-4 mb-4 rounded-xl border border-danger/40">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <Section title="Shop Settings">
          <div>
            <Label>Shop Name</Label>
            <Input value={shopName} onChange={setShopName} placeholder="German Sport" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-end mt-4">
            <NumberField label="Labor Rate ($/hr)" value={laborRate} onChange={setLaborRate} />
            <NumberField label="Parts Markup (%)" value={partsMarkup} onChange={setPartsMarkup} />
            <NumberField label="Tax %" value={tax} onChange={setTax} step="0.01" />
          </div>
        </Section>

        <Section title="Scoring Weights">
          <p className="text-xs text-text-secondary mb-4">
            How vendor offers are ranked in the auto-generate flow. Used by VendorCompareStep.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
            <Slider label={`Brand — ${brandWeight}%`} value={brandWeight} onChange={setBrandWeight} />
            <Slider label={`Price — ${priceWeight}%`} value={priceWeight} onChange={setPriceWeight} />
            <Slider label={`Distance — ${distanceWeight}%`} value={distanceWeight} onChange={setDistanceWeight} />
          </div>
        </Section>

        <Section title="API Integrations">
          <p className="text-xs text-text-secondary mb-4">
            Secrets are encrypted at rest and returned masked (last 4 chars). Leave the dots in place to
            keep an existing value; type a new value to replace it.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <IntegrationCard color="text-blue-400" title="Tekmetric">
              <SecretField label="API Key" value={tekmetricApiKey} onChange={setTekmetricApiKey} />
              <Input
                label="Shop ID"
                value={tekmetricShopId}
                onChange={setTekmetricShopId}
                placeholder="Enter Shop ID"
                small
              />
            </IntegrationCard>
            <IntegrationCard color="text-green-400" title="External Services">
              <SecretField label="ALLDATA Credentials" value={alldataCredentials} onChange={setAlldataCredentials} />
              <SecretField label="PartsLink24 Token" value={partsLinkToken} onChange={setPartsLinkToken} />
            </IntegrationCard>
            <IntegrationCard color="text-red-400" title="Twilio (SMS / Notifications)" className="md:col-span-2">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Input label="Account SID" value={twilioSid} onChange={setTwilioSid} placeholder="AC..." small />
                <SecretField label="Auth Token" value={twilioToken} onChange={setTwilioToken} />
                <Input label="Phone Number" value={twilioPhone} onChange={setTwilioPhone} placeholder="+1234567890" small />
              </div>
            </IntegrationCard>
          </div>
        </Section>

        <Section title="User Management">
          <div className="flex flex-col sm:flex-row items-start sm:items-center space-y-4 sm:space-y-0 sm:space-x-4">
            <div className="flex-1 w-full">
              <Label>Add Advisor</Label>
              <div className="flex">
                <input
                  type="text"
                  placeholder="Name"
                  value={newAdvisor}
                  onChange={(e) => setNewAdvisor(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addAdvisor()}
                  className="flex-1 bg-background border border-border text-text-primary placeholder-text-secondary/50 rounded-l-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent"
                />
                <button
                  onClick={addAdvisor}
                  className="bg-accent text-background font-bold py-3 px-6 rounded-r-lg hover:bg-accent/80 transition-colors"
                >
                  Add
                </button>
              </div>
            </div>
            <div className="flex-1 w-full flex flex-wrap gap-2 pt-6 sm:pt-0">
              {advisors.length === 0 && (
                <p className="text-sm text-text-secondary">No advisors yet.</p>
              )}
              {advisors.map((advisor) => (
                <span
                  key={advisor}
                  className="bg-primary/30 text-text-primary text-sm font-medium px-3 py-1.5 rounded-full flex items-center gap-1.5"
                >
                  {advisor}
                  <button
                    onClick={() => removeAdvisor(advisor)}
                    className="text-text-secondary hover:text-danger"
                    aria-label={`Remove ${advisor}`}
                  >
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
          </div>
        </Section>

        <Section title="Notification Templates">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <Label icon={<Mail size={16} className="mr-2" />}>Email Template</Label>
              <textarea
                value={emailTemplate}
                onChange={(e) => setEmailTemplate(e.target.value)}
                className="w-full h-48 bg-background border border-border text-text-primary rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent resize-y"
              />
            </div>
            <div>
              <Label icon={<Smartphone size={16} className="mr-2" />}>SMS Template</Label>
              <textarea
                value={smsTemplate}
                onChange={(e) => setSmsTemplate(e.target.value)}
                className="w-full h-48 bg-background border border-border text-text-primary rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent resize-y"
              />
            </div>
          </div>
          <p className="text-xs text-text-secondary mt-3">
            Use <code>{'{{customer}}'}</code> and <code>{'{{link}}'}</code> placeholders.
          </p>
        </Section>
      </div>
    </div>
  )
}

const Section = ({ title, children }) => (
  <div className="bg-surface rounded-2xl p-6 border border-border mb-6">
    <h2 className="text-xl font-bold text-text-primary mb-4">{title}</h2>
    <div className="space-y-2">{children}</div>
  </div>
)

const Label = ({ children, icon }) => (
  <label className="block text-sm font-medium text-text-secondary mb-1 flex items-center">
    {icon}
    {children}
  </label>
)

const Input = ({ label, value, onChange, placeholder = '', small = false }) => (
  <div>
    {label && <Label>{label}</Label>}
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-background border border-border text-text-primary placeholder-text-secondary/50 rounded-lg ${small ? 'p-2 text-sm' : 'p-3'} focus:outline-none focus:ring-2 focus:ring-accent`}
    />
  </div>
)

const NumberField = ({ label, value, onChange, step = '1' }) => (
  <div>
    <Label>{label}</Label>
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-background border border-border text-text-primary rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-accent"
    />
  </div>
)

const Slider = ({ label, value, onChange }) => (
  <div className="flex flex-col items-start">
    <label className="text-sm font-medium text-text-secondary mb-3">{label}</label>
    <input
      type="range"
      min="0"
      max="100"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full h-2 bg-background rounded-lg appearance-none cursor-pointer accent-accent"
    />
  </div>
)

const IntegrationCard = ({ color, title, children, className = '' }) => (
  <div className={`bg-background p-4 rounded-lg border border-border ${className}`}>
    <h3 className={`font-semibold ${color} mb-3`}>{title}</h3>
    <div className="space-y-3">{children}</div>
  </div>
)

const SecretField = ({ label, value, onChange }) => (
  <div>
    <Label>{label}</Label>
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="••••"
      className="w-full bg-surface border border-border text-text-primary placeholder-text-secondary/50 rounded p-2 focus:ring-1 focus:ring-accent text-sm font-mono"
    />
  </div>
)

export default SettingsPage
