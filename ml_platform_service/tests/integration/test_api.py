"""
Integration tests for ml_platform_service API endpoints.

Covers: health, training, registry, predictions, experiments, monitoring.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client):
        with patch("app.api.v1.endpoints.health.pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "ml_platform_service"

    @pytest.mark.asyncio
    async def test_health_degraded_on_db_error(self, client):
        with patch("app.api.v1.endpoints.health.pool") as mock_pool:
            mock_pool.acquire.side_effect = Exception("DB down")
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/api/v1/")
        assert resp.status_code == 200
        assert "ml_platform_service" in resp.json()["service"]


class TestTrainingAPI:
    @pytest.mark.asyncio
    async def test_submit_training_job(self, client):
        with patch("app.api.v1.endpoints.training.TrainingDispatcher") as mock_disp:
            mock_disp.submit = AsyncMock(return_value="started")
            resp = await client.post(
                "/api/v1/training/jobs",
                json={
                    "symbol": "RELIANCE",
                    "model_type": "xgboost",
                    "target_type": "direction",
                    "n_trials": 5,
                },
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "started"
        assert data["symbol"] == "RELIANCE"
        assert "job_id" in data

    @pytest.mark.asyncio
    async def test_submit_already_running(self, client):
        with patch("app.api.v1.endpoints.training.TrainingDispatcher") as mock_disp:
            mock_disp.submit = AsyncMock(return_value="already_running")
            resp = await client.post(
                "/api/v1/training/jobs",
                json={
                    "symbol": "INFY",
                    "model_type": "lightgbm",
                    "target_type": "direction",
                },
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "already_running"

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client):
        with patch("app.api.v1.endpoints.training.repo") as mock_repo:
            mock_repo.list_training_jobs = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/training/jobs")
        assert resp.status_code == 200
        assert resp.json() == {"jobs": [], "count": 0}

    @pytest.mark.asyncio
    async def test_list_jobs_with_symbol_filter(self, client):
        job = {"job_id": str(uuid.uuid4()), "symbol": "TCS", "model_type": "xgboost"}
        with patch("app.api.v1.endpoints.training.repo") as mock_repo:
            mock_repo.list_training_jobs = AsyncMock(return_value=[job])
            resp = await client.get("/api/v1/training/jobs?symbol=TCS")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        mock_repo.list_training_jobs.assert_called_once_with(
            symbol="TCS", model_type=None, limit=50
        )

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client):
        with patch("app.api.v1.endpoints.training.repo") as mock_repo:
            mock_repo.get_training_job = AsyncMock(return_value=None)
            resp = await client.get(f"/api/v1/training/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_job_found(self, client):
        job_id = uuid.uuid4()
        job = {"job_id": str(job_id), "symbol": "RELIANCE", "status": "completed"}
        with patch("app.api.v1.endpoints.training.repo") as mock_repo:
            mock_repo.get_training_job = AsyncMock(return_value=job)
            resp = await client.get(f"/api/v1/training/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_active_jobs(self, client):
        with patch("app.api.v1.endpoints.training.TrainingDispatcher") as mock_disp:
            mock_disp.active_jobs = MagicMock(return_value=["RELIANCE:xgboost"])
            resp = await client.get("/api/v1/training/active")
        assert resp.status_code == 200
        assert "RELIANCE:xgboost" in resp.json()["active_jobs"]


class TestRegistryAPI:
    @pytest.mark.asyncio
    async def test_list_models_empty(self, client):
        with patch("app.api.v1.endpoints.registry.repo") as mock_repo:
            mock_repo.list_model_versions = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/registry/models")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_list_champions(self, client):
        champs = [
            {"version_id": str(uuid.uuid4()), "symbol": "RELIANCE", "model_type": "xgboost"},
            {"version_id": str(uuid.uuid4()), "symbol": "RELIANCE", "model_type": "lightgbm"},
        ]
        with patch("app.api.v1.endpoints.registry.repo") as mock_repo:
            mock_repo.list_model_versions = AsyncMock(return_value=champs)
            resp = await client.get("/api/v1/registry/champions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert "RELIANCE" in data["champions"]

    @pytest.mark.asyncio
    async def test_promote_model(self, client):
        vid = uuid.uuid4()
        with patch("app.api.v1.endpoints.registry.repo") as mock_repo:
            mock_repo.promote_model = AsyncMock()
            resp = await client.post(f"/api/v1/registry/promote/{vid}")
        assert resp.status_code == 200
        assert resp.json()["promoted"] == str(vid)

    @pytest.mark.asyncio
    async def test_retire_model(self, client):
        vid = uuid.uuid4()
        with patch("app.api.v1.endpoints.registry.repo") as mock_repo:
            mock_repo.retire_model = AsyncMock()
            resp = await client.post(f"/api/v1/registry/retire/{vid}")
        assert resp.status_code == 200
        assert resp.json()["retired"] == str(vid)


class TestPredictionsAPI:
    @pytest.mark.asyncio
    async def test_predict_no_cached_features(self, client):
        with patch("app.api.v1.endpoints.predictions.get_cached_feature_vector",
                   new_callable=AsyncMock, return_value=None):
            resp = await client.post(
                "/api/v1/predict/RELIANCE",
                json={"model_types": ["xgboost"]},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_predict_no_champions(self, client):
        from app.models.domain import FeatureVector
        from datetime import datetime, timezone
        fv = FeatureVector(
            symbol="RELIANCE",
            timestamp=datetime.now(timezone.utc),
            open=1000.0, high=1020.0, low=990.0, close=1010.0, volume=500000.0,
        )
        with (
            patch("app.api.v1.endpoints.predictions.get_cached_feature_vector",
                  new_callable=AsyncMock, return_value=fv),
            patch("app.api.v1.endpoints.predictions.predict_ensemble",
                  new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.post("/api/v1/predict/RELIANCE", json={})
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_prediction_history_empty(self, client):
        with patch("app.api.v1.endpoints.predictions.repo") as mock_repo:
            mock_repo.list_predictions = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/predict/history")
        assert resp.status_code == 200
        assert resp.json() == {"predictions": [], "count": 0}

    @pytest.mark.asyncio
    async def test_get_features_not_found(self, client):
        with patch("app.api.v1.endpoints.predictions.get_cached_feature_vector",
                   new_callable=AsyncMock, return_value=None):
            resp = await client.get("/api/v1/features/UNKNOWN")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_features_found(self, client):
        from app.models.domain import FeatureVector
        from datetime import datetime, timezone
        fv = FeatureVector(
            symbol="RELIANCE",
            timestamp=datetime.now(timezone.utc),
            open=1000.0, high=1020.0, low=990.0, close=1010.0, volume=500000.0,
            rsi_14=55.0,
        )
        with patch("app.api.v1.endpoints.predictions.get_cached_feature_vector",
                   new_callable=AsyncMock, return_value=fv):
            resp = await client.get("/api/v1/features/RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert data["rsi_14"] == pytest.approx(55.0)


class TestMonitoringAPI:
    @pytest.mark.asyncio
    async def test_health_no_models(self, client):
        with (
            patch("app.api.v1.endpoints.monitoring.repo") as mock_repo,
            patch("app.api.v1.endpoints.monitoring.update_rolling_accuracy",
                  new_callable=AsyncMock, return_value=0.55),
        ):
            mock_repo.list_model_versions = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/monitoring/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_models"
        assert resp.json()["champion_models"] == 0

    @pytest.mark.asyncio
    async def test_drift_summary_empty(self, client):
        with patch("app.api.v1.endpoints.monitoring.repo") as mock_repo:
            mock_repo.list_model_versions = AsyncMock(return_value=[])
            mock_repo.get_latest_drift_report = AsyncMock(return_value=None)
            resp = await client.get("/api/v1/monitoring/drift")
        assert resp.status_code == 200
        assert resp.json()["alert_count"] == 0

    @pytest.mark.asyncio
    async def test_accuracy_endpoint(self, client):
        champ = {"symbol": "RELIANCE", "model_type": "xgboost", "version_id": str(uuid.uuid4())}
        with (
            patch("app.api.v1.endpoints.monitoring.repo") as mock_repo,
            patch("app.api.v1.endpoints.monitoring.update_rolling_accuracy",
                  new_callable=AsyncMock, return_value=0.62),
        ):
            mock_repo.list_model_versions = AsyncMock(return_value=[champ])
            resp = await client.get("/api/v1/monitoring/accuracy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["accuracy"][0]["rolling_accuracy"] == pytest.approx(0.62)


class TestExperimentsAPI:
    @pytest.mark.asyncio
    async def test_list_experiments_mlflow_unavailable(self, client):
        with patch("app.api.v1.endpoints.experiments._get_mlflow_client", return_value=None):
            resp = await client.get("/api/v1/experiments/")
        assert resp.status_code == 200
        assert resp.json()["experiments"] == []

    @pytest.mark.asyncio
    async def test_list_runs_mlflow_unavailable(self, client):
        with patch("app.api.v1.endpoints.experiments._get_mlflow_client", return_value=None):
            resp = await client.get("/api/v1/experiments/runs")
        assert resp.status_code == 200
        assert resp.json()["runs"] == []
