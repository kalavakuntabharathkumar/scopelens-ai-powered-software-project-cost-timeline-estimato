import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List

import requests
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ScopeLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
BLS_API_KEY = os.getenv("BLS_API_KEY", "")
BLS_BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Mapping of common software roles to BLS series IDs
# Format: SOC code -> BLS series ID for occupational employment and wages
ROLE_TO_BLS = {
    "software developer": "SOC15-1252",
    "project manager": "SOC11-3021",
    "qa engineer": "SOC15-1252",
    "devops engineer": "SOC15-1244",
    "data engineer": "SOC15-2051",
    "ui designer": "SOC27-3024",
    "product manager": "SOC11-3021",
    "backend engineer": "SOC15-1252",
    "frontend engineer": "SOC15-1252",
    "full stack engineer": "SOC15-1252",
    "security engineer": "SOC15-1212",
    "database administrator": "SOC13-1081",
}

# Database setup
DB_PATH = os.getenv("DB_PATH", "scopelens.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estimates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            parsed_result TEXT,
            cost_estimate REAL,
            timeline_days INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()


# --- Pydantic Models ---
class ParseRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=5000)


class ParsedRequirement(BaseModel):
    roles: List[str]
    technologies: List[str]
    complexity: str  # low, medium, high
    estimated_months: int


class WageData(BaseModel):
    occupation: str
    mean_hourly: float
    mean_annual: float


class EstimateResponse(BaseModel):
    total_cost: float
    timeline_days: int
    breakdown: List[dict]
    currency: str = "USD"


# --- BLS API Client ---
class BLSClient:
    """Client for BLS OEWS API to fetch wage data."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def get_wage_data(self, series_id: str) -> Optional[WageData]:
        """Fetch wage data for a BLS series ID."""
        if not self.api_key:
            logger.warning("BLS_API_KEY not set, using fallback wages")
            return self._fallback_wage(series_id)

        payload = {
            "seriesid": [series_id],
            "registrationkey": self.api_key,
        }
        try:
            resp = self.session.post(BLS_BASE_URL, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "REQUEST_SUCCEEDED":
                logger.error(f"BLS API error: {data}")
                return self._fallback_wage(series_id)

            series = data.get("Results", {}).get("series", [])
            if not series:
                return self._fallback_wage(series_id)

            # Get latest data point
            items = series[0].get("data", [])
            if not items:
                return self._fallback_wage(series_id)

            latest = items[0]
            annual_wage = float(latest.get("value", 0))
            hourly_wage = annual_wage / 2080  # 2080 work hours/year

            return WageData(
                occupation=series_id,
                mean_hourly=round(hourly_wage, 2),
                mean_annual=round(annual_wage, 2),
            )
        except requests.RequestException as e:
            logger.error(f"BLS API request failed: {e}")
            return self._fallback_wage(series_id)

    def _fallback_wage(self, series_id: str) -> WageData:
        """Fallback wage data when BLS API is unavailable."""
        fallbacks = {
            "SOC15-1252": WageData("software developer", 56.0, 116480),
            "SOC11-3021": WageData("project manager", 48.0, 100000),
            "SOC15-1244": WageData("devops engineer", 60.0, 125000),
            "SOC15-2051": WageData("data engineer", 55.0, 114400),
            "SOC27-3024": WageData("ui designer", 42.0, 87360),
            "SOC15-1212": WageData("security engineer", 65.0, 135200),
            "SOC13-1081": WageData("database administrator", 45.0, 93600),
        }
        return fallbacks.get(series_id, WageData("unknown", 50.0, 104000))


# --- OpenAI Parser ---
class ProjectParser:
    """Parses natural-language project descriptions using OpenAI."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key) if api_key else None

    def parse(self, description: str) -> ParsedRequirement:
        """Extract structured requirements from a project description."""
        if not self.client:
            logger.warning("OPENAI_API_KEY not set, using heuristic parsing")
            return self._heuristic_parse(description)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a project requirements extractor. Given a natural-language "
                            "project description, extract: roles needed, technologies used, "
                            "complexity (low/medium/high), and estimated months. "
                            "Return valid JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f'Parse this project description: "{description}"\n'
                            'Return JSON: {"roles": [...], "technologies": [...], '
                            '"complexity": "low|medium|high", "estimated_months": int}'
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=500,
            )
            result = json.loads(response.choices[0].message.content)
            return ParsedRequirement(**result)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"OpenAI parse error: {e}")
            return self._heuristic_parse(description)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise HTTPException(status_code=503, detail="OpenAI service unavailable")

    def _heuristic_parse(self, description: str) -> ParsedRequirement:
        """Fallback parser when OpenAI is unavailable."""
        desc_lower = description.lower()
        roles = []
        for role in ROLE_TO_BLS.keys():
            if role in desc_lower:
                roles.append(role)
        if not roles:
            roles = ["software developer"]
        complexity = "medium"
        if len(description) > 500:
            complexity = "high"
        elif len(description) < 100:
            complexity = "low"
        return ParsedRequirement(
            roles=roles,
            technologies=["web"],
            complexity=complexity,
            estimated_months=3 if complexity == "low" else 6 if complexity == "medium" else 9,
        )


# --- Cost Estimation Engine ---
class CostEstimator:
    """Estimates project cost using BLS wage data."""

    def __init__(self, bls_client: BLSClient):
        self.bls = bls_client

    def estimate(self, parsed: ParsedRequirement) -> EstimateResponse:
        """Generate cost estimate from parsed requirements."""
        breakdown = []
        total_cost = 0.0

        for role in parsed.roles:
            series_id = ROLE_TO_BLS.get(role, "SOC15-1252")
            wage = self.bls.get_wage_data(series_id)

            # Calculate person-months based on complexity
            complexity_multiplier = {"low": 0.5, "medium": 1.0, "high": 1.5}
            multiplier = complexity_multiplier.get(parsed.complexity, 1.0)
            person_months = parsed.estimated_months * multiplier

            # Assume 160 hours/month
            total_hours = person_months * 160
            role_cost = total_hours * wage.mean_hourly

            breakdown.append({
                "role": role,
                "hourly_rate": wage.mean_hourly,
                "total_hours": total_hours,
                "cost": round(role_cost, 2),
                "person_months": person_months,
            })
            total_cost += role_cost

        timeline_days = int(parsed.estimated_months * 30 * multiplier)

        return EstimateResponse(
            total_cost=round(total_cost, 2),
            timeline_days=timeline_days,
            breakdown=breakdown,
        )


# --- Initialize services ---
bls_client = BLSClient(BLS_API_KEY)
parser = ProjectParser(OPENAI_API_KEY)
estimator = CostEstimator(bls_client)


# --- API Endpoints ---
@app.post("/api/parse", response_model=ParsedRequirement)
async def parse_project(req: ParseRequest):
    """Parse a natural-language project description."""
    try:
        result = parser.parse(req.description)
        # Save to DB
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO estimates (description, parsed_result) VALUES (?, ?)",
            (req.description, json.dumps(result.dict())),
        )
        conn.commit()
        conn.close()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Parse error: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse project description")


@app.post("/api/estimate", response_model=EstimateResponse)
async def estimate_project(req: ParseRequest):
    """Full pipeline: parse description and generate cost estimate."""
    parsed = parser.parse(req.description)
    estimate = estimator.estimate(parsed)

    # Update DB with estimate
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE estimates SET parsed_result=?, cost_estimate=?, timeline_days=? WHERE description=?",
        (json.dumps(parsed.dict()), estimate.total_cost, estimate.timeline_days, req.description),
    )
    conn.commit()
    conn.close()

    return estimate


@app.get("/api/wages/{occupation}")
async def get_wage(occupation: str):
    """Get wage data for a specific occupation."""
    series_id = ROLE_TO_BLS.get(occupation.lower())
    if not series_id:
        raise HTTPException(status_code=404, detail=f"Occupation '{occupation}' not found")
    wage = bls_client.get_wage_data(series_id)
    return wage


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "bls_configured": bool(BLS_API_KEY),
        "openai_configured": bool(OPENAI_API_KEY),
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
