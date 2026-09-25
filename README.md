# ScopeLens — AI-Powered Software Project Cost & Timeline Estimator

A full-stack web application that combines OpenAI's API with real BLS wage data to generate accurate cost estimates, schedules, and budgets from natural-language project descriptions.

## Features

- **Natural-language parsing**: Uses OpenAI API to extract team roles, technologies, and complexity from project descriptions
- **Cost estimation**: Cross-references parsed requirements against real BLS OEWS wage data for 800+ occupations
- **Itemized budgets & schedules**: Produces detailed cost breakdowns and timeline estimates
- **Automated tests**: 45+ test cases covering API integrations and error handling

## Tech Stack

- Python (FastAPI) backend
- React frontend
- OpenAI API for NLP parsing
- BLS OEWS API (api.bls.gov/publicAPI/v2/) for wage data
- SQLite for persistence

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-key"
export BLS_API_KEY="your-bls-key"
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm start
```

## API Keys

- **OpenAI**: Sign up at https://platform.openai.com, set `OPENAI_API_KEY` env var
- **BLS**: Register at https://api.bls.gov, set `BLS_API_KEY` env var

## Real Data Sources

- BLS OEWS API: `https://api.bls.gov/publicAPI/v2/timeseries/data/`
- OpenAI GPT-4 for intent classification and requirement extraction