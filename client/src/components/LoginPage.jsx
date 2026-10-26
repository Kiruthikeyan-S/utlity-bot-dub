import React, { useState } from 'react';
import { Bot, Mail, Lock, User, AlertCircle, Loader2, LogIn, UserPlus } from 'lucide-react';
import { signInWithGoogle, loginWithEmail, registerWithEmail } from '../firebase';

export default function LoginPage() {
  const [mode, setMode] = useState('signin'); // 'signin' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleGoogleSignIn = async () => {
    setError(null);
    setLoading(true);
    const result = await signInWithGoogle();
    setLoading(false);
    if (!result.success) {
      setError(result.error);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password.trim()) {
      setError('Please provide both email and password.');
      return;
    }

    setLoading(true);

    if (mode === 'signin') {
      const result = await loginWithEmail(email.trim(), password);
      setLoading(false);
      if (!result.success) {
        setError(result.error);
      }
    } else {
      const result = await registerWithEmail(email.trim(), password, displayName.trim());
      setLoading(false);
      if (!result.success) {
        setError(result.error);
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col justify-center items-center px-4 py-12">
      
      {/* Brand Header */}
      <div className="flex flex-col items-center mb-8 text-center">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20 text-white mb-3">
          <Bot className="w-8 h-8" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Utility Bot</h1>
        <p className="text-xs text-slate-500 mt-1">
          {mode === 'signin' ? 'Sign in to access your dashboard' : 'Create an account to get started'}
        </p>
      </div>

      {/* Main Login Card */}
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl shadow-slate-200/60 border border-slate-200/80 p-6 sm:p-8">
        
        {/* Tab Switcher */}
        <div className="flex rounded-xl bg-slate-100 p-1 mb-6">
          <button
            type="button"
            onClick={() => { setMode('signin'); setError(null); }}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              mode === 'signin'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => { setMode('signup'); setError(null); }}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-all cursor-pointer ${
              mode === 'signup'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            Register
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-5 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-start space-x-2.5 animate-in fade-in">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-rose-600" />
            <div className="flex-1 font-medium leading-relaxed">{error}</div>
          </div>
        )}

        {/* Google Sign In */}
        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full flex items-center justify-center space-x-3 px-4 py-2.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-xs transition hover:border-slate-300 disabled:opacity-50 cursor-pointer active:scale-[0.99]"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
            />
            <path
              fill="#EA4335"
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
            />
          </svg>
          <span>Continue with Google</span>
        </button>

        {/* Divider */}
        <div className="relative my-5 flex items-center justify-center">
          <div className="border-t border-slate-200 w-full"></div>
          <span className="bg-white px-3 text-[11px] font-medium text-slate-400 uppercase tracking-wider absolute">
            or with email
          </span>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'signup' && (
            <div>
              <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider mb-1">
                Full Name
              </label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Kiruthikeyan"
                  className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-hidden focus:border-indigo-500 focus:bg-white transition"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider mb-1">
              Email Address
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-hidden focus:border-indigo-500 focus:bg-white transition"
              />
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider mb-1">
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 focus:outline-hidden focus:border-indigo-500 focus:bg-white transition"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-2.5 px-4 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-700 hover:to-indigo-700 text-white rounded-xl text-xs font-semibold shadow-md shadow-indigo-500/20 transition flex items-center justify-center space-x-2 disabled:opacity-50 cursor-pointer active:scale-[0.99]"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Please wait...</span>
              </>
            ) : mode === 'signin' ? (
              <>
                <LogIn className="w-4 h-4" />
                <span>Sign In</span>
              </>
            ) : (
              <>
                <UserPlus className="w-4 h-4" />
                <span>Create Account</span>
              </>
            )}
          </button>
        </form>

        {/* Footer helper */}
        <div className="mt-5 text-center">
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signin' ? 'signup' : 'signin');
              setError(null);
            }}
            className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold transition cursor-pointer"
          >
            {mode === 'signin'
              ? "Don't have an account? Sign up"
              : 'Already have an account? Sign in'}
          </button>
        </div>

      </div>

      <footer className="mt-8 text-center text-xs text-slate-400">
        Utility Bot • Secure Document Extraction & Verification
      </footer>
    </div>
  );
}
