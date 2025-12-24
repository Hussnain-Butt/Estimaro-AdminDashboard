// src/components/ui/Toast.jsx
// Toast notification component for displaying errors and success messages

import { useState, useEffect, createContext, useContext } from 'react'

const ToastContext = createContext(null)

// Toast types with styles
const toastStyles = {
    success: 'bg-success text-background border-success',
    error: 'bg-error text-white border-error',
    warning: 'bg-warning text-background border-warning',
    info: 'bg-info text-white border-info'
}

const toastIcons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ'
}

// Individual Toast Component
const Toast = ({ id, type, title, message, onClose }) => {
    useEffect(() => {
        const timer = setTimeout(() => {
            onClose(id)
        }, 5000) // Auto-close after 5 seconds

        return () => clearTimeout(timer)
    }, [id, onClose])

    return (
        <div
            className={`flex items-start gap-3 p-4 rounded-lg border shadow-lg mb-3 animate-slide-in ${toastStyles[type]}`}
            role="alert"
        >
            <span className="text-xl font-bold">{toastIcons[type]}</span>
            <div className="flex-1">
                {title && <p className="font-bold text-sm">{title}</p>}
                <p className="text-sm">{message}</p>
            </div>
            <button
                onClick={() => onClose(id)}
                className="text-xl font-bold opacity-70 hover:opacity-100 transition-opacity"
            >
                ×
            </button>
        </div>
    )
}

// Toast Container Component
const ToastContainer = ({ toasts, removeToast }) => {
    if (toasts.length === 0) return null

    return (
        <div className="fixed top-4 right-4 z-50 max-w-md w-full">
            {toasts.map((toast) => (
                <Toast
                    key={toast.id}
                    {...toast}
                    onClose={removeToast}
                />
            ))}
        </div>
    )
}

// Toast Provider Component
export const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([])

    const addToast = (type, title, message) => {
        const id = Date.now()
        setToasts(prev => [...prev, { id, type, title, message }])
        return id
    }

    const removeToast = (id) => {
        setToasts(prev => prev.filter(toast => toast.id !== id))
    }

    // Convenience methods
    const toast = {
        success: (message, title = 'Success') => addToast('success', title, message),
        error: (message, title = 'Error') => addToast('error', title, message),
        warning: (message, title = 'Warning') => addToast('warning', title, message),
        info: (message, title = 'Info') => addToast('info', title, message)
    }

    return (
        <ToastContext.Provider value={toast}>
            {children}
            <ToastContainer toasts={toasts} removeToast={removeToast} />
        </ToastContext.Provider>
    )
}

// Hook to use toast
export const useToast = () => {
    const context = useContext(ToastContext)
    if (!context) {
        throw new Error('useToast must be used within a ToastProvider')
    }
    return context
}

export default Toast
