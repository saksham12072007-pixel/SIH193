import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try { await login(email, password); navigate("/", { replace: true }); }
    catch (exception) { setError(exception instanceof ApiError ? exception.message : "Unable to sign in. Please try again."); }
    finally { setSubmitting(false); }
  }

  return <div className="auth-page"><div className="auth-art"><div className="brand"><span className="brand-mark">K</span><div><strong>KrishiMitra</strong><small>Crop intelligence</small></div></div><div className="art-copy"><span className="eyebrow">THE FIELD, UNDERSTOOD</span><h1>Better signals.<br /><em>Better harvests.</em></h1><p>Turn satellite observations and field knowledge into timely, explainable action.</p></div><div className="art-foot"><span>Satellite-led advisory platform</span><span>India / 2026</span></div></div><div className="auth-panel"><div className="auth-form-wrap"><span className="eyebrow">INSTITUTIONAL ACCESS</span><h2>Welcome back</h2><p className="muted-text">Sign in to your operations workspace.</p>{typeof location.state?.message === "string" && <div className="notice"><strong>{location.state.message}</strong></div>}<form onSubmit={submit}><label>Email address<input required type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@organization.org" /></label><label>Password<input required type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Enter your password" /></label>{error && <div className="form-error">{error}</div>}<button className="primary-button" disabled={submitting}>{submitting ? "Signing in..." : "Sign in"}<span>→</span></button></form><p className="form-note">Need an account? <Link to="/signup">Create a field officer account</Link></p></div></div></div>;
}
