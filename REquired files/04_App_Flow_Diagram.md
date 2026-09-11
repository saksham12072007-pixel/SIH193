# 04 — App Flow Diagram
## Navigation & Interaction Logic

Cross-references: `02_Product_Requirements_Document.md` (features), `05_UIUX_Design_Brief.md`
(screen/message design), `07_System_Architecture_Diagram.md` (backend flow that these
interactions trigger).

Note: per `03_Technical_Requirements_Document.md` §5, the farmer-facing interface is SMS/USSD-first
(no app required for MVP). "Screens" below refer to (a) SMS/USSD message states for farmers and
(b) actual UI screens for the optional smartphone/WhatsApp path and the institutional dashboard.

---

### 1. Farmer Onboarding Flow (SMS/USSD)

```
[Farmer sends "JOIN" or dials USSD code]
        |
        v
[System] "Welcome! Reply with your name."
        |
        v
[Farmer replies with name]
        |
        v
[System] "Choose language: 1-Hindi 2-Marathi 3-Telugu ..."
        |
        v
[Farmer selects language]
        |
        v
[System] "Do you consent to share your phone number and plot location for
          crop advisories? Reply YES to continue."
        |
   DECISION: consent given?
     NO  -> [System] "Registration cancelled. Text JOIN anytime to restart." -> END
     YES -> continue
        |
        v
[System] "Share your plot location (missed call to <number> or reply with
          village name if no GPS)."
        |
        v
[Farmer shares location or village name]
        |
        v
[System] "What crop is growing on this plot? Reply with crop name/code."
        |
        v
[Farmer replies crop]
        |
        v
[System] "When did you sow this crop? Reply DD/MM."
        |
        v
[Farmer replies sowing date]
        |
        v
[System] "Registration complete! You'll get advisories for your [crop] plot
          in [language]. Reply HELP anytime for options."
        |
        v
[Plot stored -> enters scheduled satellite ingestion cycle, see 07_...md]
```

**Decision points:**
- If consent is not given → registration halts; no plot or PII beyond phone number is stored
  (PRD AC1.2).
- If GPS location cannot be captured (feature-phone missed-call flow fails) → fallback to
  village-name entry (PRD F2), with a system flag on the plot record noting "coarse location" —
  this affects the buffer-polygon default (TRD §3.2) and is surfaced to institutional dashboard
  users as a data-quality flag.

---

### 2. Advisory Generation & Delivery Flow (system-triggered, not farmer-initiated)

```
[Scheduled ingestion cycle completes for a plot] (07_...md §2)
        |
        v
[ML Decision Engine produces: class + confidence + reason-code] (TRD §3)
        |
   DECISION: is class "No Action"?
     YES -> [Log advisory, no SMS sent by default — farmer can still query via HISTORY]
     NO  -> continue
        |
        v
   DECISION: is class "Irrigate Now — Stress Alert" (critical)?
     YES -> [Trigger SMS] AND [If farmer opted into IVR: trigger voice call] (PRD F7)
     NO  -> [Trigger SMS only]
        |
        v
[SMS Delivery Layer sends templated message in farmer's language] (05_...md §3-4)
        |
   DECISION: delivery confirmed by gateway?
     YES -> [Mark delivered, log timestamp]
     NO  -> [Retry once within 30 min] (TRD §7)
              |
         DECISION: retry succeeds?
           YES -> [Mark delivered]
           NO  -> [Mark failed, flag for manual review] (PRD AC5.3)
        |
        v
[Farmer may reply within 72 hrs] -> see Feedback Flow (Section 3 below)
```

**Decision points:**
- "No Action" advisories are logged but **not** sent as SMS by default — this enforces the alert-
  fatigue cap (PRD F7, AC7.3) and the "no message is more valuable than a needless one" design
  principle. A farmer can always pull status via "HISTORY" or "STATUS <plot-id>".
- Critical alerts ("Irrigate Now") get dual-channel delivery (SMS + IVR) if the farmer has opted
  into IVR — this is the one case where more than one channel fires for a single advisory event.

---

### 3. Farmer Feedback / Reply Flow

```
[Farmer receives advisory SMS with reply options: "1-Irrigated 2-Not needed 3-Crop damaged"]
        |
        v
[Farmer sends a reply within 72 hrs]
        |
   DECISION: is reply a recognized digit (1/2/3)?
     YES -> [Match reply to originating advisory record] -> [Log feedback] (PRD F9, AC9.1)
              |
              v
        [System] "Thank you, recorded." (confirmation sent back)
     NO  -> [System] "Sorry, reply with 1, 2, or 3 to confirm your last advisory."
              (clarifying prompt, PRD AC9.2 — feedback is never silently dropped)
        |
        v
[Feedback record available to weekly ML retraining batch job] (TRD §3.5)
```

---

### 4. Farmer Self-Service Commands (always available, not part of a linear flow)

| Command | Response |
|---|---|
| `MY PLOTS` | List of registered plots with nickname/ID and crop (PRD AC2.4) |
| `HISTORY <plot-id>` | Last 3 advisories for that plot (PRD AC8.1) |
| `STATUS <plot-id>` | Current advisory class for that plot, including "No Action" if applicable |
| `PAUSE <plot-id>` / `RESUME <plot-id>` | Stops/restarts advisories for that plot (PRD AC7.1) |
| `LANG <code>` | Changes language preference, effective next message (PRD AC6.2) |
| `HELP` | Lists all available commands in the farmer's current language |

Each of these is a stateless request-response pair — no multi-step flow required, since they are
issued by an already-registered farmer.

---

### 5. Institutional Dashboard Flow (web UI, PRD F10)

```
[Institutional user logs in] (email/password + optional MFA, TRD §5)
        |
        v
[Dashboard home] -> map view, defaulted to user's assigned geography
        |
        v
   DECISION: user selects a village/block cell
     -> [Aggregated view]: % of plots per advisory class, trend over last 4 cycles
        (minimum 5-plot aggregation threshold enforced, PRD AC10.1)
        |
        v
[User may export aggregated view] (read-only, no edit actions available in MVP, PRD AC10.3)
```

**Decision point:** if a selected cell has fewer than the minimum aggregation threshold (5 plots),
the dashboard shows "insufficient data for this area" rather than rendering a cell that could
de-anonymize an individual farmer.

---

### 6. WhatsApp / Web Companion Flow (optional, smartphone-owning farmers — P2)

Mirrors the SMS onboarding and advisory flow (Sections 1–3) with richer content where useful (e.g.,
a small map snapshot of the plot alongside the advisory text), but **never as a replacement** for
SMS — SMS is always sent regardless of WhatsApp opt-in, per the farmer-first/no-single-point-of-
failure design principle (`01_...md` §5).
