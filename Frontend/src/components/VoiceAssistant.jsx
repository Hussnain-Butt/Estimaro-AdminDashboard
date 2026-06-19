// Voice Assistant — a STANDALONE page so Sergio can talk to the feedback
// assistant directly, WITHOUT first building an estimate. The assistant listens,
// replies in voice, asks clarifying questions, and the whole conversation is
// saved as feedback (input_mode='voice_agent') so it shows up on the Feedback
// page like any other advisor input.
//
// `useConversation` requires a `ConversationProvider` ancestor, so the exported
// page is a thin wrapper that supplies one; the logic lives in the inner panel.
import React, { useRef, useState } from 'react'
import { useConversation, ConversationProvider } from '@elevenlabs/react'
import { MicrophoneIcon, StopIcon, ChatBubbleLeftRightIcon } from '@heroicons/react/24/outline'
import { getVoiceAgentUrl, submitConversation } from '../services/api'
import { useToast } from './ui/Toast'

const VoiceAssistantInner = () => {
  const toast = useToast()
  const [callState, setCallState] = useState('idle') // idle | connecting | live | saving
  const [turns, setTurns] = useState([])              // {role:'you'|'assistant', text}
  const [sent, setSent] = useState(false)
  const turnsRef = useRef([])
  const convoIdRef = useRef(null)

  const saveConversation = async () => {
    const t = turnsRef.current
    if (!t.length) { setCallState('idle'); return }
    const transcript = t
      .map((x) => `${x.role === 'you' ? 'Advisor' : 'Assistant'}: ${x.text}`)
      .join('\n')
    setCallState('saving')
    const res = await submitConversation({
      transcript,
      conversation_id: typeof convoIdRef.current === 'string' ? convoIdRef.current : null,
      // No estimate anchored — this is general/direct feedback.
      estimate_source: 'general',
      advisor_name: 'Sergio',
    })
    setCallState('idle')
    if (res.success) { setSent(true); toast.success('Conversation saved — thank you!', 'Logged') }
    else toast.error(res.error || 'Could not save the conversation', 'Error')
  }

  const conversation = useConversation({
    onConnect: (info) => {
      if (info?.conversationId) convoIdRef.current = info.conversationId
      setCallState('live')
    },
    onDisconnect: () => saveConversation(),
    onError: () => { toast.error('Voice agent hiccup — please try again.'); setCallState('idle') },
    onMessage: (m) => {
      if (!m?.message) return
      const role = m.source === 'user' ? 'you' : 'assistant'
      turnsRef.current = [...turnsRef.current, { role, text: m.message }]
      setTurns(turnsRef.current)
    },
  })

  const startCall = async () => {
    setSent(false); turnsRef.current = []; setTurns([]); convoIdRef.current = null
    setCallState('connecting')
    const urlRes = await getVoiceAgentUrl()
    if (!urlRes.success) { toast.error(urlRes.error || 'Voice agent unavailable'); setCallState('idle'); return }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch { toast.error('Mic permission needed to talk to the assistant.'); setCallState('idle'); return }
    try {
      // startSession returns void in v1.7 — the conversationId arrives via onConnect.
      await conversation.startSession({
        signedUrl: urlRes.data.signed_url,
        connectionType: 'websocket',
        dynamicVariables: {
          vehicle: 'general (not tied to one estimate)',
          service: 'general feedback and improvements for Estimaro',
          total: 'N/A',
        },
      })
    } catch {
      toast.error('Could not start the voice agent — please try again.')
      setCallState('idle')
    }
  }

  const endCall = async () => { try { await conversation.endSession() } catch { /* noop */ } }

  const inCall = callState === 'connecting' || callState === 'live'

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <ChatBubbleLeftRightIcon className="h-7 w-7 text-primary" />
          Talk to the Assistant
        </h1>
        <p className="text-text-secondary mt-1">
          Tell us anything about Estimaro — what to fix, what to improve, what's working.
          The assistant listens, replies, and notes everything. No estimate needed.
        </p>
      </div>

      {/* Call panel */}
      <div className="bg-surface border border-border rounded-2xl p-8 flex flex-col items-center text-center">
        <div
          className={`relative h-28 w-28 rounded-full flex items-center justify-center mb-5 transition-colors ${
            callState === 'live'
              ? (conversation.isSpeaking ? 'bg-primary/20' : 'bg-success/15')
              : 'bg-card'
          }`}
        >
          {callState === 'live' && (
            <span
              className={`absolute inset-0 rounded-full animate-ping ${
                conversation.isSpeaking ? 'bg-primary/30' : 'bg-success/20'
              }`}
            />
          )}
          {inCall
            ? <StopIcon className="h-12 w-12 text-error relative" />
            : <MicrophoneIcon className="h-12 w-12 text-primary relative" />}
        </div>

        <p className="text-sm font-medium text-text-primary mb-4 h-5">
          {callState === 'idle' && (sent ? '✓ Conversation saved — thank you!' : 'Ready when you are')}
          {callState === 'connecting' && 'Connecting…'}
          {callState === 'live' && (conversation.isSpeaking ? '🔊 Assistant is speaking…' : '🟢 Listening — go ahead')}
          {callState === 'saving' && 'Saving conversation…'}
        </p>

        {!inCall ? (
          <button
            onClick={startCall}
            disabled={callState === 'saving'}
            className="px-6 py-3 rounded-xl bg-primary text-background font-semibold flex items-center gap-2 disabled:opacity-50 hover:opacity-90 transition"
          >
            <MicrophoneIcon className="h-5 w-5" /> Start talking
          </button>
        ) : (
          <button
            onClick={endCall}
            className="px-6 py-3 rounded-xl bg-error text-white font-semibold flex items-center gap-2 hover:opacity-90 transition"
          >
            <StopIcon className="h-5 w-5" /> End call
          </button>
        )}
      </div>

      {/* Live transcript */}
      {turns.length > 0 && (
        <div className="bg-surface border border-border rounded-2xl p-5">
          <h2 className="text-sm font-semibold text-text-secondary mb-3">Conversation</h2>
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {turns.map((t, i) => (
              <div key={i} className={`flex ${t.role === 'you' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${
                    t.role === 'you'
                      ? 'bg-primary text-background rounded-br-sm'
                      : 'bg-card text-text-primary rounded-bl-sm'
                  }`}
                >
                  {t.text}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const VoiceAssistant = () => (
  <ConversationProvider>
    <VoiceAssistantInner />
  </ConversationProvider>
)

export default VoiceAssistant
