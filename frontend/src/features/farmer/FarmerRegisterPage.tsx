import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../../lib/api";
import type { Farmer } from "../../types";

export function FarmerRegisterPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ phone_number: "", name: "", preferred_language: "hi", state: "", district: "" });
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!consent) { setError("Consent is required to register."); return; }
    setSubmitting(true);
    try {
      await api.post<Farmer>("/farmers/register", { ...form, consent_given: consent, registration_channel: "web" });
      navigate("/farmer/login", { replace: true, state: { message: "Registration complete. Sign in with your phone number." } });
    } catch (exception) {
      setError(exception instanceof ApiError ? exception.message : "Unable to register. Please try again.");
    } finally { setSubmitting(false); }
  }
  const update = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm(current => ({ ...current, [key]: event.target.value }));
  return <div className="auth-page"><div className="auth-art"><div className="brand"><span className="brand-mark">K</span><div><strong>KrishiMitra</strong><small>Farmer advisory</small></div></div><div className="art-copy"><span className="eyebrow">FARMER ACCESS</span><h1>Your farm.<br /><em>Your signal.</em></h1><p>Register once to view your plots and receive clear, timely crop advice.</p></div><div className="art-foot"><span>Satellite-led advisory platform</span><span>India / 2026</span></div></div><div className="auth-panel"><div className="auth-form-wrap"><span className="eyebrow">FARMER REGISTRATION</span><h2>Create your profile</h2><p className="muted-text">Use the phone number linked to your farm.</p><form onSubmit={submit}><label>Phone number<input required type="tel" value={form.phone_number} onChange={update("phone_number")} placeholder="+91 98765 43210" /></label><label>Name<input value={form.name} onChange={update("name")} placeholder="Your name" /></label><div className="form-grid"><label>Language<select value={form.preferred_language} onChange={update("preferred_language")}><option value="hi">Hindi</option><option value="en">English</option><option value="mr">Marathi</option><option value="te">Telugu</option></select></label><label>State<input value={form.state} onChange={update("state")} placeholder="State" /></label><label>District<input value={form.district} onChange={update("district")} placeholder="District" /></label></div><label className="checkbox-label"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /> I agree to receive crop advisories and allow my farm data to be used for this service.</label>{error && <div className="form-error" role="alert">{error}</div>}<button className="primary-button" disabled={submitting}>{submitting ? "Registering..." : "Register"}<span>→</span></button></form><p className="form-note">Already registered? <Link to="/farmer/login">Sign in</Link></p></div></div></div>;
}
