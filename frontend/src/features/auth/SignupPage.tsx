import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../../lib/api";

interface SignupResponse {
  user_id: string;
  email: string;
  role: string;
  assigned_geography: Record<string, string[]>;
}

export function SignupPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await api.post<SignupResponse>("/institutional/signup", { email, password });
      navigate("/login", { replace: true, state: { message: "Account created. Sign in to continue." } });
    } catch (exception) {
      setError(exception instanceof ApiError ? exception.message : "Unable to create the account. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="auth-page"><div className="auth-art"><div className="brand"><span className="brand-mark">K</span><div><strong>KrishiMitra</strong><small>Crop intelligence</small></div></div><div className="art-copy"><span className="eyebrow">FIELD OPERATIONS</span><h1>Join the<br /><em>signal network.</em></h1><p>Create a field-officer account to work within your assigned institutional scope.</p></div><div className="art-foot"><span>Self-signup access</span><span>India / 2026</span></div></div><div className="auth-panel"><div className="auth-form-wrap"><span className="eyebrow">INSTITUTIONAL ACCESS</span><h2>Create account</h2><p className="muted-text">Self-signup creates a field officer account. An administrator can provision other roles.</p><form onSubmit={submit}><label>Email address<input required type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="you@organization.org" /></label><label>Password<input required minLength={8} type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="At least 8 characters" /></label><label>Confirm password<input required minLength={8} type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} placeholder="Repeat your password" /></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="primary-button" disabled={submitting}>{submitting ? "Creating account..." : "Create account"}<span>→</span></button></form><p className="form-note">Already registered? <Link to="/login">Return to sign in</Link></p></div></div></div>;
}
