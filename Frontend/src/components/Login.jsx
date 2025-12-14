import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const Login = ({ onLogin }) => {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const navigate = useNavigate()

    const handleSubmit = (e) => {
        e.preventDefault()
        if (username === 'Estimaro' && password === 'Estimaro') {
            onLogin()
            navigate('/')
        } else {
            setError('Invalid credentials. Please try again.')
        }
    }

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-4">
            <div className="bg-surface border border-border rounded-xl shadow-2xl p-8 w-full max-w-md">
                <div className="text-center mb-8">
                    <h1 className="text-3xl font-bold text-text-primary mb-2">Estimaro</h1>
                    <p className="text-text-secondary">Please sign in to continue</p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-6">
                    <div>
                        <label className="block text-sm font-medium text-text-secondary mb-2">
                            Username
                        </label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            className="bg-background text-text-primary placeholder-text-secondary/50 w-full px-4 py-3 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent transition-all duration-300"
                            placeholder="Enter username"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-text-secondary mb-2">
                            Password
                        </label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="bg-background text-text-primary placeholder-text-secondary/50 w-full px-4 py-3 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent transition-all duration-300"
                            placeholder="Enter password"
                        />
                    </div>

                    {error && (
                        <div className="text-danger text-sm text-center font-medium bg-danger/10 py-2 rounded">
                            {error}
                        </div>
                    )}

                    <button
                        type="submit"
                        className="w-full bg-accent hover:bg-accent-dark text-background font-bold py-3 px-6 rounded-lg transition-all shadow-lg shadow-accent/20"
                    >
                        Sign In
                    </button>
                </form>
            </div>
        </div>
    )
}

export default Login
