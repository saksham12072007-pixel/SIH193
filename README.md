KrishiSetu

Smart, Satellite-Driven Agricultural Decision Support

Smart India Hackathon 2026
Problem Statement: 26193 — Student Innovation: Agriculture
Theme: Agriculture, FoodTech & Rural Development

Overview

KrishiSetu is a satellite and AI-powered agricultural advisory platform designed to help farmers make better, plot-specific irrigation decisions.

The system combines Sentinel-1 SAR, Sentinel-2 optical imagery, weather data, soil information, crop stage and farmer feedback to estimate crop/soil water stress and provide a simple, actionable advisory through a mobile application and low-bandwidth channels such as SMS/IVR.

Core Idea

Observe → Analyse → Decide → Advise → Learn

Instead of providing generic irrigation recommendations, KrishiSetu generates decisions for the specific plot, crop and current conditions.

Problem

Farmers often depend on fixed irrigation schedules or generic recommendations because:

Soil moisture is not continuously available at plot level.

Weather and rainfall conditions change rapidly.

Satellite, weather and soil data are available separately.

Smallholder farmers may have limited access to digital tools.

Existing agricultural information can be difficult to convert into a clear farm-level action.

KrishiSetu addresses this gap by converting multiple data sources into an explainable, plot-level irrigation advisory.

Solution

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

Key Features

1. Plot-Level Intelligence

GPS-based plot registration

Crop and sowing-date information

Plot-specific analysis

Agro-climatic context

2. Satellite-Based Monitoring

Sentinel-1 SAR: VV/VH backscatter and change features

Sentinel-2: Red, NIR, Green, SWIR and vegetation indices

NDVI, NDWI, EVI and related features

Cloud-aware processing

3. Multi-Source Data Fusion

Rainfall

Temperature

Humidity

ET₀

Weather forecast

Soil properties

Crop growth stage

SMAP regional context

4. AI/ML Decision Support

Two-stage architecture:

Stage 1
EO + Weather + Soil/Crop Features
              ↓
Root-Zone Soil Moisture / CWSI
              ↓
Stage 2
Moisture + Crop Stage + Rainfall + ET₀ + Soil Context
              ↓
No Action / Monitor / Irrigate Soon / Irrigate Now

5. Explainable Advisory

Every actionable recommendation can include:

Decision

Reason code

Confidence

Relevant crop/plot context

6. Farmer-Centric Delivery

Mobile application

SMS

Optional IVR

Local-language advisory

Feedback mechanism

7. Institutional Dashboard

Aggregate and geography-scoped information for authorized institutional users:

Crop stress

Irrigation risk

Advisory distribution

Trends

Model health

Technology Stack

Layer

Technology

Mobile / Frontend

React Native / Web companion

Backend

Python, FastAPI

Database

PostgreSQL + PostGIS

Satellite Processing

Google Earth Engine

ML

Python, XGBoost / scikit-learn

Geospatial

PostGIS, GeoPandas

Weather

IMD / NASA POWER / Open-Meteo

Satellite

Sentinel-1, Sentinel-2, SMAP

Scheduling

Cron / Airflow

Communication

SMS / IVR Gateway

Dashboard

React + Leaflet

System Architecture

┌──────────────────────┐
│   FARMER / PLOT      │
│ GPS • Crop • Soil    │
│ Sowing Date • Consent│
└──────────┬───────────┘
           ↓
┌─────────────────────────────────┐
│       DATA SOURCES              │
│ Sentinel-1 • Sentinel-2         │
│ Weather • SMAP • Soil • Crop    │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│ INGESTION & PREPROCESSING        │
│ Cloud Mask • QA • Alignment     │
│ Spatial Processing • Validation │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│      FEATURE ENGINEERING        │
│ NDVI • NDWI • EVI • VV • VH     │
│ Rainfall • ET₀ • Kc • AWC       │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│       ML / DECISION ENGINE      │
│ Soil Moisture • CWSI • Stress   │
│ Decision • Confidence • Reason  │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│       ADVISORY ENGINE           │
│ Crop × Reason × Language        │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│ MOBILE APP • SMS • IVR          │
└──────────┬──────────────────────┘
           ↓
┌─────────────────────────────────┐
│ FEEDBACK → EVALUATION →         │
│ MODEL IMPROVEMENT                │
└─────────────────────────────────┘

Repository Structure

KrishiSetu/
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

Getting Started

Prerequisites

Python 3.11+

Node.js

PostgreSQL + PostGIS

Google Earth Engine access

Required weather/satellite API credentials

Backend

git clone <repository-url>
cd KrishiSetu

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload

Frontend

cd frontend
npm install
npm run dev

Create your local environment file from:

.env.example

Never commit API keys, passwords, private keys or production credentials.

Advisory Classes

Class

Meaning

No Action

Current conditions do not justify irrigation

Monitor

Continue monitoring conditions

Irrigate Soon

Irrigation may be required shortly

Irrigate Now

Immediate water-stress condition detected

What Makes KrishiSetu Different

KrishiSetu focuses on the complete decision pipeline, not only satellite visualization:

Multi-source satellite + weather + soil + crop fusion

Plot-specific water-stress estimation

Explainable irrigation decisions

Confidence-aware recommendations

Mobile + SMS/IVR accessibility

Farmer feedback loop

Model evaluation and continuous improvement

Aggregate institutional intelligence

Expected Impact

KrishiSetu aims to support:

More efficient irrigation

Reduced unnecessary water usage

Earlier identification of crop water stress

Better farm-level decision making

Improved accessibility for smallholder farmers

Data-driven agricultural monitoring for institutions

Impact values will be validated through pilot and field evaluation and should not be treated as measured results until validation is complete.

Project Scope

The initial project architecture is designed for a pilot deployment and can be extended from village/block-level monitoring to district and state-level agricultural intelligence.

The system is designed to remain farmer-centric, explainable, scalable and accessible under limited connectivity.

SIH 2026

Hackathon: Smart India Hackathon 2026
Problem Statement: 26193
Domain: Agriculture, FoodTech & Rural Development
Project: KrishiSetu

Team

Team Name: std::survive 

Member

Role

Shankar Adhikary 

Backend & Architecture

Arnendu Biswas 

GIS & Satellite Data

Saksham Sharma 

AI/ML

Pratham Bhardwaj

Integration & Communication

Saumya Mishra

Frontend & Dashboard

Riti Patel

Research and testing 

Disclaimer

KrishiSetu is a decision-support system. Final agronomic thresholds, model performance and field-level impact must be validated with appropriate agricultural experts and real-world pilot data before production deployment.

