
# KrishiSetu

### Smart, Satellite-Driven Agricultural Decision Support

**Smart India Hackathon 2026**  
**Problem Statement:** 26193 — Student Innovation: Agriculture  
**Theme:** Agriculture, FoodTech & Rural Development

---

## Overview

**KrishiSetu** is a satellite and AI-powered agricultural advisory platform designed to help farmers make better, plot-specific irrigation decisions.

The system combines **Sentinel-1 SAR, Sentinel-2 optical imagery, weather data, soil information, crop stage, and farmer feedback** to estimate crop/soil water stress and provide simple, actionable advisories through a mobile application and low-bandwidth channels such as **SMS and IVR**.

### Core Idea

> **Observe → Analyse → Decide → Advise → Learn**

Instead of providing generic irrigation recommendations, KrishiSetu generates decisions based on the **specific plot, crop, and current environmental conditions**.

---

# Problem Statement

Farmers often depend on fixed irrigation schedules or generic recommendations because:

- Soil moisture is not continuously available at plot level.
- Weather and rainfall conditions change rapidly.
- Satellite, weather, and soil data are available separately.
- Smallholder farmers may have limited access to digital agricultural tools.
- Existing agricultural information can be difficult to convert into a clear farm-level action.

### Our Approach

KrishiSetu addresses this gap by converting multiple data sources into an **explainable, plot-level irrigation advisory**.

---

# Solution

KrishiSetu follows an end-to-end decision pipeline:

```text
Farmer & Plot Registration
            ↓
Satellite + Weather + Soil + Crop Data
            ↓
Data Ingestion & Quality Control
            ↓
Feature Engineering
            ↓
Soil Moisture / Crop Stress Estimation
            ↓
Irrigation Decision Engine
            ↓
Reason + Confidence
            ↓
Farmer Advisory
            ↓
Mobile App / SMS / IVR
            ↓
Farmer Feedback
            ↓
Model Evaluation & Improvement
````

---

# Key Features

## 1. Plot-Level Intelligence

* GPS-based plot registration
* Crop and sowing-date information
* Plot-specific analysis
* Agro-climatic context

## 2. Satellite-Based Monitoring

### Sentinel-1 SAR

* VV/VH backscatter
* Temporal change features
* Useful for monitoring surface conditions under varying cloud conditions

### Sentinel-2 Optical

* Red
* NIR
* Green
* SWIR
* Vegetation and water-related indices

### Derived Indices

* NDVI
* NDWI
* EVI
* SAVI
* Related temporal features

The processing pipeline includes cloud and quality-control handling.

---

# 3. Multi-Source Data Fusion

KrishiSetu combines multiple environmental and agricultural data sources:

| Data Category | Inputs                                  |
| ------------- | --------------------------------------- |
| Satellite     | Sentinel-1, Sentinel-2                  |
| Weather       | Rainfall, Temperature, Humidity, ET₀    |
| Forecast      | Weather forecast                        |
| Soil          | Soil properties, AWC                    |
| Crop          | Crop type, growth stage, Kc             |
| Context       | SMAP regional soil-moisture information |
| Farmer        | Plot information and feedback           |

This fusion enables more context-aware decisions than relying on a single data source.

---

# 4. AI/ML Decision Support

KrishiSetu uses a two-stage decision architecture.

### Stage 1 — Water Stress Estimation

```text
EO + Weather + Soil/Crop Features
                ↓
Root-Zone Soil Moisture / CWSI
                ↓
             Confidence
```

### Stage 2 — Irrigation Decision

```text
Soil Moisture / CWSI
        +
Crop Stage
        +
Rainfall Forecast
        +
ET₀
        +
Soil Context
        ↓
Irrigation Decision
```

### Decision Classes

```text
No Action
     │
     ├── Monitor
     │
     ├── Irrigate Soon
     │
     └── Irrigate Now
```

---

# 5. Explainable Advisory

Each actionable recommendation can contain:

* **Decision**
* **Reason Code**
* **Confidence Score**
* **Crop Context**
* **Plot Context**

This helps farmers understand **why** an advisory was generated rather than receiving a recommendation without explanation.

---

# 6. Farmer-Centric Delivery

KrishiSetu is designed for different levels of digital connectivity.

### Delivery Channels

* Mobile application
* SMS
* Optional IVR
* Local-language advisories
* Farmer feedback mechanism

The goal is to make agricultural intelligence accessible even in **low-connectivity environments**.

---

# 7. Institutional Dashboard

Authorized institutional users can access **aggregate and geography-scoped information** such as:

* Crop stress
* Irrigation risk
* Advisory distribution
* Agricultural trends
* Model health

The dashboard is designed to support institutional monitoring without exposing individual farmer information by default.

---

# Technology Stack

| Layer                 | Technology                    |
| --------------------- | ----------------------------- |
| Mobile / Frontend     | React Native                  |
| Web Companion         | React                         |
| Backend               | Python, FastAPI               |
| Database              | PostgreSQL + PostGIS          |
| Satellite Processing  | Google Earth Engine           |
| Machine Learning      | Python, XGBoost, scikit-learn |
| Geospatial Processing | PostGIS, GeoPandas            |
| Weather Data          | IMD / NASA POWER / Open-Meteo |
| Satellite Data        | Sentinel-1, Sentinel-2, SMAP  |
| Scheduling            | Cron / Airflow                |
| Communication         | SMS / IVR Gateway             |
| Dashboard             | React + Leaflet               |

---

# System Architecture

```text
┌──────────────────────────────────────┐
│          FARMER / PLOT               │
│                                      │
│ GPS • Crop • Soil • Sowing Date      │
│ Consent • Plot Information           │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│            DATA SOURCES              │
│                                      │
│ Sentinel-1 • Sentinel-2              │
│ Weather • SMAP • Soil • Crop Data    │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│       INGESTION & PREPROCESSING      │
│                                      │
│ Cloud Mask • Quality Control         │
│ Spatial Processing • Date Alignment  │
│ Validation                           │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│         FEATURE ENGINEERING          │
│                                      │
│ NDVI • NDWI • EVI • SAVI             │
│ VV • VH • Rainfall • ET₀             │
│ Kc • AWC • Crop Stage                │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│          ML / DECISION ENGINE        │
│                                      │
│ Soil Moisture • CWSI • Stress        │
│ Decision • Confidence • Reason Code  │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│           ADVISORY ENGINE            │
│                                      │
│ Crop × Reason × Language × Context   │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│       FARMER DELIVERY CHANNELS       │
│                                      │
│ Mobile App • SMS • IVR               │
└───────────────────┬──────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│       FEEDBACK & IMPROVEMENT         │
│                                      │
│ Farmer Feedback → Evaluation         │
│ → Model Improvement                  │
└──────────────────────────────────────┘
```

---

# Repository Structure

```text
KrishiSetu/
│
├── app/
│   ├── routers/
│   ├── services/
│   ├── models/
│   ├── schemas/
│   └── db/
│
├── frontend/
│
├── ml/
│   ├── training/
│   ├── inference/
│   └── evaluation/
│
├── gis/
│   ├── ingestion/
│   └── feature_engineering/
│
├── dashboard/
│
├── tests/
│
├── docs/
│
├── requirements.txt
├── .env.example
└── README.md
```

---

# Getting Started

## Prerequisites

Make sure the following are installed:

* Python 3.11+
* Node.js
* PostgreSQL
* PostGIS
* Google Earth Engine access
* Required weather and satellite API credentials

---

## Backend Setup

```bash
git clone <repository-url>
cd KrishiSetu

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload
```

---

## Frontend Setup

```bash
cd frontend

npm install
npm run dev
```

Create your local environment configuration using:

```text
.env.example
```

> **Never commit API keys, passwords, private keys, or production credentials to GitHub.**

---

# Advisory Classes

| Advisory          | Meaning                                      |
| ----------------- | -------------------------------------------- |
| **No Action**     | Current conditions do not justify irrigation |
| **Monitor**       | Continue monitoring the plot                 |
| **Irrigate Soon** | Irrigation may be required shortly           |
| **Irrigate Now**  | Immediate water-stress condition detected    |

---

# What Makes KrishiSetu Different?

KrishiSetu focuses on the **complete agricultural decision pipeline**, rather than only providing satellite imagery or visualization.

### Key Differentiators

* Multi-source satellite + weather + soil + crop fusion
* Plot-specific water-stress estimation
* Explainable irrigation decisions
* Confidence-aware recommendations
* Mobile + SMS/IVR accessibility
* Local-language advisory support
* Farmer feedback loop
* Model evaluation and improvement
* Aggregate institutional intelligence
* Decision traceability through reason codes and model information

---

# Expected Impact

KrishiSetu aims to support:

* More efficient irrigation
* Reduced unnecessary water usage
* Earlier identification of crop water stress
* Better farm-level decision making
* Improved accessibility for smallholder farmers
* Data-driven agricultural monitoring for institutions

> **Note:** Impact values will be validated through pilot and field evaluation. They should not be treated as measured results until validation is completed.

---

# Project Scope

The initial architecture is designed for a **pilot deployment** and can be extended from:

```text
Village
   ↓
Block
   ↓
District
   ↓
State
```

The platform is designed to remain:

* Farmer-centric
* Explainable
* Scalable
* Data-driven
* Accessible under limited connectivity

---

# SIH 2026

| Field             | Details                                   |
| ----------------- | ----------------------------------------- |
| Hackathon         | Smart India Hackathon 2026                |
| Problem Statement | 26193                                     |
| Domain            | Agriculture, FoodTech & Rural Development |
| Project           | KrishiSetu                                |
| Team              | std::survive                              |

---

# Team

| Member               | Role                        |
| -------------------- | --------------------------- |
| **Shankar Adhikary** | Backend & Architecture      |
| **Arnendu Biswas**   | GIS & Satellite Data        |
| **Saksham Sharma**   | AI/ML                       |
| **Pratham Bhardwaj** | Integration & Communication |
| **Saumya Mishra**    | Frontend & Dashboard        |
| **Riti Patel**       | Research & Testing          |

---

# Future Scope

The platform can be further extended with:

* Additional crop types
* More regional languages
* District/state-level deployment
* Advanced crop-stress analytics
* Improved satellite time-series modelling
* Expanded farmer feedback datasets
* Field-level validation
* Integration with additional agricultural services

---

# Disclaimer

KrishiSetu is a **decision-support system** and not a replacement for professional agronomic advice.

Final agronomic thresholds, model performance, irrigation recommendations, and field-level impact must be validated through appropriate **agricultural expertise, field trials, and real-world pilot data** before production deployment.

---


```

