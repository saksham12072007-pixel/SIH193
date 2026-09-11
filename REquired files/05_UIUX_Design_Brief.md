# 05 — UI/UX Design Brief

Cross-references: `04_App_Flow_Diagram.md` (interaction sequences this design supports),
`02_Product_Requirements_Document.md` (feature-level requirements), `03_Technical_Requirements_Document.md` §5 (auth/platform).

Scope note: the **primary interface is SMS/USSD**, not a graphical app, per the farmer-first
principle. This brief covers (1) SMS/IVR design — the most important surface — (2) the optional
WhatsApp/web companion for smartphone users, and (3) the institutional dashboard.

---

### 1. Design Principles (specific to this product)
1. **The message IS the interface.** For most farmers, there is no screen — only an SMS. Every
   design decision starts there, not with a mockup.
2. **Legibility over branding.** No decorative elements that cost SMS characters or dashboard
   load time without adding comprehension.
3. **Symbol-assisted, not symbol-dependent.** A single emoji/symbol (e.g., ⚠️) may reinforce
   urgency for farmers with camera/smart-feature phones, but the text must stand alone without it.
4. **One primary action per surface.** An SMS asks for exactly one reply; a dashboard screen shows
   one primary decision (map + one filter), not a control panel.
5. **Big touch targets, high contrast, minimal text entry** on any graphical surface — field
   conditions mean bright sunlight, dirty/wet hands, and older low-end devices.

---

### 2. SMS Format & Tone (the core deliverable)

**Format constraints:**
- Target ≤2 SMS segments (≤320 characters for Unicode/regional script; ≤320 GSM-7 characters for
  Latin-script languages) per message.
- Structure: **[urgency symbol if critical] [farmer's plot/crop reference] [the action, stated
  first] [the reason, one short clause] [the reply options]**.

**Tone:**
- Direct, respectful, never alarmist for non-critical classes.
- Second-person, active voice ("Irrigate today" not "Irrigation is recommended").
- No raw index numbers unless they materially help ("moisture is low" beats "SM=18.3%" for a
  farmer, but see accessibility note below on when a simple number can build trust over time).

**Sample messages (English gloss — production templates are authored natively per language, not
translated at send-time, per TRD §3.4 and PRD F6):**

| Class | Sample SMS |
|---|---|
| Irrigate Now — Stress Alert | ⚠️ Wheat plot (Plot 2): Soil moisture is low, no rain expected in 2 days. Irrigate today. Reply 1-Done, 2-Not needed. |
| Irrigate Soon | Wheat plot (Plot 2): Moisture is dropping. Plan to irrigate in the next 2-3 days. Reply 1-Done, 2-Not needed. |
| Monitor | Wheat plot (Plot 2): Crop looks normal but moisture is falling. Watch over next 2-3 days. |
| No Action | *(not sent by default — see App Flow §2; available on-demand via STATUS command)* Wheat plot (Plot 2): Healthy, enough moisture. No action needed. |
| Data unavailable | Wheat plot (Plot 2): No clear satellite reading this cycle (cloud cover). We'll check again in [N] days. |

**Reply-option consistency:** every actionable advisory uses the same digit mapping (1 = action
taken, 2 = not needed, 3 = crop already damaged) across all crops/languages, so farmers build
muscle memory rather than re-learning per message type.

---

### 3. IVR (Voice) Design

- Used as a **redundant channel** for critical alerts only (opt-in, PRD F7), not a full parallel
  system.
- Script structure mirrors the SMS: greeting → plot/crop reference → action → reason → how to
  confirm ("Press 1 to confirm you've irrigated").
- Delivered via text-to-speech in the farmer's selected language, or agronomist-recorded audio for
  the MVP pilot language(s) where TTS quality in that regional language/dialect is uncertain
  (flagged as a build-time decision — evaluate available TTS voice quality per language before
  committing to TTS-only for a given language).
- Call length target: under 30 seconds, single message, no multi-level phone menu.

---

### 4. SMS Template Governance (design-process requirement, not a runtime feature)
- Every (crop × reason-code × language) combination has exactly one vetted template, stored and
  versioned in the backend (`06_Backend_Schema.md`), never generated freeform at send-time.
- New templates go through: draft (by content/localization owner) → agronomist review (accuracy
  of the recommendation and reasoning) → native-speaker review (naturalness, no awkward
  transliteration) → sign-off before activation.
- No template may be activated without passing all three review steps — this is enforced as a
  workflow status field, not a suggestion (ties to PRD AC6.3).

---

### 5. Screen Layouts — WhatsApp/Web Companion (P2, smartphone-owning farmers)

**5.1 Login/Registration screen**
- Single field: phone number → OTP-free (session tied to WhatsApp identity, or simple phone-number
  entry for the web form used by KVK field agents on the farmer's behalf).
- Large, single-column layout; no side navigation; language selector as the first visible control
  (icon + text label, not text-only, to support pre-literacy recognition).

**5.2 Plot Registration screen**
- Map view defaulted to the user's current GPS location with a single "drop pin here" button.
- Crop selector as a **visual grid of crop icons + names** (not a dropdown) — recognition is
  faster than reading for many users.
- Sowing date via a simple calendar picker, defaulting to "today" to minimize taps.

**5.3 Advisory Display screen**
- Advisory class shown as a large color-coded banner (see palette below) with the same short
  action text used in the SMS — consistency between channels is intentional, not duplicated
  design effort.
- A single expandable "Why?" section reveals the reason-code explanation in plain language plus
  the underlying trend (e.g., small NDVI sparkline) for farmers who want more detail — collapsed
  by default to keep the primary screen simple.

**5.4 History View**
- Simple reverse-chronological list, one card per advisory: date, class (color-coded), one-line
  reason, farmer's own reply if given.
- No infinite scroll complexity needed at this data volume — a paginated list of 10 is sufficient.

---

### 6. Visual Design System (companion app + dashboard)

**Color palette (semantic, colorblind-safe pairing with icons/text, never color-alone):**
| Class | Color | Icon |
|---|---|---|
| No Action | Green (#2E7D32) | ✓ checkmark |
| Monitor | Amber/Yellow (#F9A825) | eye/watch icon |
| Irrigate Soon | Orange (#EF6C00) | droplet outline |
| Irrigate Now — Stress Alert | Red (#C62828) | filled droplet + warning triangle |
| Data unavailable | Grey (#757575) | cloud/question icon |

**Typography:**
- A font with strong regional-script (Devanagari, Telugu, Tamil, etc.) rendering support and high
  legibility at small sizes — verify actual font choice against the target script set at build
  time rather than assuming a single global font covers all planned languages.
- Minimum body text size: 16px equivalent on mobile screens (field-use legibility, not desktop
  defaults).

**Icon style:** simple, filled (not thin-line) icons for maximum visibility in bright outdoor
light and on lower-quality screens.

---

### 7. Accessibility Requirements

- **Diverse literacy levels:** every advisory class pairs color + icon + short text — never relies
  on text or color alone to convey meaning.
- **Button sizing:** minimum 44x44px touch targets on any graphical surface, generous spacing
  between adjacent actionable elements (field conditions: wet/dirty hands, older devices).
- **Low bandwidth:** companion web/WhatsApp screens must load meaningfully under 2G/3G conditions —
  no heavy imagery beyond the essential map tile and crop icon set; map tiles cached/simplified
  where possible.
- **Script rendering:** all supported regional scripts tested for correct rendering on common
  low-cost Android devices before a language is marked "supported" (ties to PRD F6).
- **SMS-first equivalence:** any information available on the companion app/dashboard that affects
  a farmer's core decision (the advisory itself) must also be fully available via SMS — the app is
  additive richness, never a required channel for the core decision.

---

### 8. Institutional Dashboard UI Notes (PRD F10)
- Map-first layout: village/block polygons color-coded by dominant advisory class this cycle.
- A single filter bar: crop type, date range, advisory class — no nested/multi-level filter UI.
- Aggregation-threshold "insufficient data" cells are shown as a distinct neutral grey/hatched
  pattern, not simply hidden, so users understand data exists but is protected (supports PRD
  AC10.1's privacy requirement transparently rather than silently).
