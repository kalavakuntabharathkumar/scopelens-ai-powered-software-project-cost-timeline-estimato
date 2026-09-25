import pytest
import json
import sqlite3
import os
from unittest.mock import patch, MagicMock

from main import app, init_db, DB_PATH, BLSClient, ProjectParser, CostEstimator, ParsedRequirement, WageData

@pytest.fixture
def client():
    # Use in-memory test DB
    global DB_PATH
    old_db = DB_PATH
    DB_PATH = ":memory:"
    init_db()
    from fastapi.testclient import TestClient
    test_client = TestClient(app)
    yield test_client
    DB_PATH = old_db


class TestBLSClient:
    def test_fallback_wage_when_no_key(self):
        """BLS client returns fallback data when API key is missing."""
        client = BLSClient(api_key="")
        wage = client.get_wage_data("SOC15-1252")
        assert wage is not None
        assert wage.mean_annual > 0

    def test_fallback_wage_unknown_series(self):
        """Fallback handles unknown series IDs."""
        client = BLSClient(api_key="")
        wage = client.get_wage_data("SOC99-9999")
        assert wage.occupation == "unknown"
        assert wage.mean_hourly == 50.0

    @patch('main.requests.Session')
    def test_bls_api_success(self, mock_session):
        """BLS client parses successful API response correctly."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [{
                    "seriesID": "SOC15-1252",
                    "data": [{"value": "116480"}]
                }]
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.return_value.post.return_value = mock_resp

        client = BLSClient(api_key="test_key")
        wage = client.get_wage_data("SOC15-1252")
        assert wage.mean_annual == 116480
        assert wage.mean_hourly == round(116480 / 2080, 2)

    @patch('main.requests.Session')   
    def test_bls_api_failure_returns_fallback(self, mock_session):
        """BLS client falls back on request exception."""
        mock_session.return_value.post.side_effect = Exception("Network error")
        client = BLSClient(api_key="test_key")
        wage = client.get_wage_data("SOC15-1252")
        assert wage.mean_annual > 0


class TestProjectParser:
    def test_heuristic_parse_no_api_key(self):
        """Heuristic parser works without OpenAI key."""
        parser = ProjectParser(api_key="")
        result = parser.parse("Build a web app with React and Python")
        assert isinstance(result.roles, list)
        assert len(result.roles) > 0
        assert result.complexity in ["low", "medium", "high"]

    @patch('main.OpenAI')
    def test_openai_parse_success(self, mock_openai):
        """OpenAI parser returns structured data."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "roles": ["software developer"],
            "technologies": ["React"],
            "complexity": "medium",
            "estimated_months": 4
        })
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        parser = ProjectParser(api_key="test_key")
        result = parser.parse("Build a React web app")
        assert result.complexity == "medium"
        assert result.estimated_months == 4

    @patch('main.OpenAI')
    def test_openai_parse_invalid_json_fallback(self, mock_openai):
        """Parser falls back on invalid JSON from OpenAI."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "not valid json"
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        parser = ProjectParser(api_key="test_key")
        result = parser.parse("Build something")
        assert isinstance(result.roles, list)


class TestCostEstimator:
    def test_estimate_produces_valid_output(self):
        """Estimator generates cost breakdown with positive values."""
        bls = BLSClient(api_key="")
        estimator = CostEstimator(bls)
        parsed = ParsedRequirement(
            roles=["software developer"],
            technologies=["Python"],
            complexity="medium",
            estimated_months=6
        )
        estimate = estimator.estimate(parsed)
        assert estimate.total_cost > 0
        assert estimate.timeline_days > 0
        assert len(estimate.breakdown) == 1
        assert estimate.breakdown[0]["cost"] > 0

    def test_estimate_multiple_roles(self):
        """Estimator handles multiple roles correctly."""
        bls = BLSClient(api_key="")
        estimator = CostEstimator(bls)
        parsed = ParsedRequirement(
            roles=["software developer", "project manager"],
            technologies=["Python", "React"],
            complexity="low",
            estimated_months=3
        )
        estimate = estimator.estimate(parsed)
        assert len(estimate.breakdown) == 2
        assert estimate.total_cost > 0


class TestAPIEndpoints:
    def test_health_check(self, client):
        """Health endpoint returns ok status."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_parse_endpoint(self, client):
        """Parse endpoint returns structured requirements."""
        resp = client.post("/api/parse", json={
            "description": "Build a web application with React frontend and Python backend"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert "technologies" in data
        assert "complexity" in data

    def test_parse_endpoint_validation(self, client):
        """Parse endpoint validates input length."""
        resp = client.post("/api/parse", json={"description": "short"})
        assert resp.status_code == 422

    def test_estimate_endpoint(self, client):
        """Estimate endpoint returns full cost breakdown."""
        resp = client.post("/api/estimate", json={
            "description": "Build a simple website with frontend and backend"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] > 0
        assert data["timeline_days"] > 0
        assert len(data["breakdown"]) > 0

    def test_wage_endpoint(self, client):
        """Wage endpoint returns salary data for known occupation."""
        resp = client.get("/api/wages/software%20developer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mean_annual"] > 0

    def test_wage_endpoint_not_found(self, client):
        """Wage endpoint returns 404 for unknown occupation."""
        resp = client.get("/api/wages/nonexistent")
        assert resp.status_code == 404
