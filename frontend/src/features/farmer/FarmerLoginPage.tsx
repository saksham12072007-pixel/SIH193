import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { useFarmerAuth } from "../../lib/farmerAuth";

export function FarmerLoginPage() {
  const { login } = useFarmerAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [phone, setPhone] = useState("");
  const [channel, setChannel] = useState<"sms" | "ussd">("sms");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setSubmitting(true);
    try { await login(phone, channel); navigate("/farmer", { replace: true }); }
    catch (exception) { setError(exception instanceof ApiError ? exception.message : "Unable to sign in. Please try again."); }
    finally { setSubmitting(false); }
  }
  return <div className="auth-page"><div className="auth-art"><div className="brand"><span className="brand-mark">K</span><div><strong>KrishiMitra</strong><small>Farmer advisory</small></div></div><div className="art-copy"><span className="eyebrow">FARMER ACCESS</span><h1>Advice that<br /><em>travels with you.</em></h1><p>Check your plots and the latest irrigation guidance from any device.</p></div></div><div className="auth-panel"><div className="auth-form-wrap"><span className="eyebrow">FARMER SIGN IN</span><h2>Welcome back</h2><p className="muted-text">Sign in with your registered phone number.</p>{typeof location.state?.message === "string" && <div className="notice"><strong>{location.state.message}</strong></div>}<form onSubmit={submit}><label>Phone number<input required type="tel" value={phone} onChange={event => setPhone(event.target.value)} placeholder="+91 98765 43210" /></label><label>Session channel<select value={channel} onChange={event => setChannel(event.target.value as "sms" | "ussd")}><option value="sms">SMS</option><option value="ussd">USSD</option></select></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="primary-button" disabled={submitting}>{submitting ? "Signing in..." : "Sign in"}<span>→</span></button></form><p className="form-note">New to KrishiMitra? <Link to="/farmer/register">Register as a farmer</Link></p></div></div></div>;
}
