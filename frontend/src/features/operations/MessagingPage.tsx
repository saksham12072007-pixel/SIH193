import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../../lib/api";

type Channel = "sms" | "whatsapp" | "ivr";

interface DeliveryResult {
  status: string;
  provider?: string;
  message_id?: string;
  recipient?: string;
}

interface RetryResult {
  status: string;
  messages_retried: number;
}

export function MessagingPage() {
  const [channel, setChannel] = useState<Channel>("sms");
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("");

  const send = useMutation({
    mutationFn: async (): Promise<DeliveryResult> => {
      if (channel === "whatsapp") {
        return api.post<DeliveryResult>("/sms/whatsapp/send", {
          farmer_phone: phone,
          message_body: message,
        });
      }
      if (channel === "ivr") {
        return api.post<DeliveryResult>("/sms/ivr", {
          farmer_phone: phone,
          script: message,
        });
      }
      return api.post<DeliveryResult>("/sms/send", {
        farmer_phone: phone,
        message_body: message,
      });
    },
    onSuccess: () => {
      setMessage("");
    },
  });

  const retry = useMutation({
    mutationFn: () => api.post<RetryResult>("/internal/sms/retry"),
  });

  const errorMessage = (error: unknown) =>
    error instanceof ApiError ? error.message : "The messaging request could not be completed.";

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">FIELD COMMUNICATIONS</span>
          <h2>Messaging controls</h2>
          <p>Send approved farmer communications through the configured provider.</p>
        </div>
        <button className="button secondary" onClick={() => retry.mutate()} disabled={retry.isPending}>
          {retry.isPending ? "Retrying…" : "Retry failed messages"}
        </button>
      </div>

      <div className="content-grid">
        <form className="panel form-panel" onSubmit={(event) => { event.preventDefault(); send.mutate(); }}>
          <div className="panel-heading">
            <div><span className="eyebrow">NEW OUTBOUND MESSAGE</span><h3>Reach a farmer</h3></div>
          </div>
          <label>
            Channel
            <select value={channel} onChange={(event) => setChannel(event.target.value as Channel)}>
              <option value="sms">SMS</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="ivr">IVR voice call</option>
            </select>
          </label>
          <label>
            Farmer phone number
            <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+91…" required />
          </label>
          <label>
            {channel === "ivr" ? "Voice script" : "Message"}
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={5} maxLength={1000} required />
          </label>
          <div className="form-actions">
            <span className="muted">{message.length}/1000 characters</span>
            <button className="button primary" type="submit" disabled={send.isPending}>
              {send.isPending ? "Sending…" : `Send ${channel.toUpperCase()}`}
            </button>
          </div>
          {send.isError && <p className="form-error" role="alert">{errorMessage(send.error)}</p>}
          {send.isSuccess && <p className="form-success" role="status">Request accepted by {send.data.provider ?? "the messaging provider"}.</p>}
        </form>

        <div className="panel">
          <div className="panel-heading">
            <div><span className="eyebrow">DELIVERY OPERATIONS</span><h3>Provider actions</h3></div>
          </div>
          <p className="muted">Use retry after a provider outage to reprocess failed outbound messages. Delivery receipts are reconciled by the backend webhook.</p>
          {retry.isError && <p className="form-error" role="alert">{errorMessage(retry.error)}</p>}
          {retry.isSuccess && <p className="form-success" role="status">{retry.data.messages_retried} message(s) retried.</p>}
          <div className="notice-card">
            <strong>Privacy and consent</strong>
            <span>Only contact farmers through approved numbers and institutionally authorized workflows.</span>
          </div>
        </div>
      </div>
    </section>
  );
}
