"""Tests for GET /runs/{run_id}/positions/sectors.

Run directories are fabricated under ``tmp_path`` mirroring the layout the
run-detail handler expects (``RUNS_DIR/<run_id>/artifacts/positions.csv``).

After the US/CA refactor the endpoint only classifies each symbol's asset
class (``us_equity`` / ``ca_equity`` / ``index``); the A-share industry lookup
via Eastmoney is gone with ``sector_tool``, so ``industry`` is always ``None``
and no network call is ever made.
"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient

import api_server

RUN_ID = "run_20260801_120000"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_server, "RUNS_DIR", tmp_path / "runs")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _make_run(tmp_path: Path, header: str, rows: list[str] | None = None) -> Path:
    run_dir = tmp_path / "runs" / RUN_ID
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    lines = [header, *(rows or [])]
    (artifacts / "positions.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


# ============================================================================
# Endpoint: happy path
# ============================================================================


def test_positions_sectors_classifies_us_ca_index(tmp_path: Path, monkeypatch) -> None:
    _make_run(
        tmp_path,
        "timestamp,AAPL.US,TD.TO,^SPX",
        ["2026-08-01T00:00:00,0.5,0.3,0.2"],
    )
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["run_id"] == RUN_ID
    assert payload["cached"] is False
    assert payload["resolved_at"].endswith("Z")
    assert payload["symbols"]["AAPL.US"] == {
        "asset_class": "us_equity",
        "industry": None,
        "industry_source": None,
    }
    assert payload["symbols"]["TD.TO"] == {
        "asset_class": "ca_equity",
        "industry": None,
        "industry_source": None,
    }
    assert payload["symbols"]["^SPX"]["asset_class"] == "index"
    assert payload["unresolved"] == []
    assert payload["total_symbols"] == 3
    assert payload["symbol_limit"] == 200

    cache_path = tmp_path / "runs" / RUN_ID / "artifacts" / "sector_map.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["symbols"]["AAPL.US"]["asset_class"] == "us_equity"


# ============================================================================
# Endpoint: cache behaviour
# ============================================================================


def test_positions_sectors_cache_hit_makes_zero_network_calls(tmp_path: Path, monkeypatch) -> None:
    _make_run(tmp_path, "timestamp,AAPL.US", ["2026-08-01T00:00:00,1.0"])
    client = _client(tmp_path, monkeypatch)

    first = client.get(f"/runs/{RUN_ID}/positions/sectors")
    assert first.status_code == 200
    assert first.json()["cached"] is False

    second = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert second.status_code == 200
    payload = second.json()
    assert payload["cached"] is True
    assert payload["resolved_at"] == first.json()["resolved_at"]
    assert payload["symbols"]["AAPL.US"]["asset_class"] == "us_equity"


def test_positions_sectors_refresh_bypasses_cache(tmp_path: Path, monkeypatch) -> None:
    _make_run(tmp_path, "timestamp,AAPL.US", ["2026-08-01T00:00:00,1.0"])
    client = _client(tmp_path, monkeypatch)

    first = client.get(f"/runs/{RUN_ID}/positions/sectors")
    second = client.get(f"/runs/{RUN_ID}/positions/sectors?refresh=1")

    assert first.json()["cached"] is False
    assert second.json()["cached"] is False
    assert second.json()["symbols"]["AAPL.US"]["asset_class"] == "us_equity"


def test_positions_sectors_corrupt_cache_recomputes(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "timestamp,AAPL.US", ["2026-08-01T00:00:00,1.0"])
    (run_dir / "artifacts" / "sector_map.json").write_text("{not json", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cached"] is False
    assert payload["symbols"]["AAPL.US"]["asset_class"] == "us_equity"


# ============================================================================
# Endpoint: degenerate runs
# ============================================================================


def test_missing_positions_csv_returns_note(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "runs" / RUN_ID).mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }


def test_empty_positions_csv_returns_note(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "positions.csv").write_text("", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols"] == {}
    assert payload["note"] == "no positions artifact"


def test_unknown_run_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/runs/no-such-run/positions/sectors")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run no-such-run not found"


def test_symlinked_artifacts_dir_returns_no_positions_note(tmp_path: Path, monkeypatch) -> None:
    """A symlinked artifacts dir is rejected, mirroring the factor scan."""
    real_artifacts = tmp_path / "real_artifacts"
    real_artifacts.mkdir()
    (real_artifacts / "positions.csv").write_text(
        "timestamp,AAPL.US\n2026-08-01T00:00:00,1.0\n", encoding="utf-8"
    )
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "artifacts").symlink_to(real_artifacts)
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }


def test_symlinked_cache_file_rejected_without_write_through(tmp_path: Path, monkeypatch) -> None:
    """A symlinked ``sector_map.json`` is rejected like a symlinked artifacts dir.

    The artifacts directory itself is real here; only the cache file is a
    symlink. Neither the cache read nor the cache rewrite may follow it, or a
    planted symlink becomes a write primitive outside the run directory.
    """
    run_dir = _make_run(tmp_path, "timestamp,AAPL.US", ["2026-08-01T00:00:00,1.0"])
    target = tmp_path / "elsewhere.json"
    target.write_text("sentinel", encoding="utf-8")
    (run_dir / "artifacts" / "sector_map.json").symlink_to(target)
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }
    assert target.read_text(encoding="utf-8") == "sentinel"


def test_symlinked_positions_csv_rejected_without_read(tmp_path: Path, monkeypatch) -> None:
    """A symlinked ``positions.csv`` is rejected like a symlinked artifacts dir.

    The artifacts directory itself is real here; only positions.csv is a
    symlink. Following it would disclose the target file's header line in the
    response, so the endpoint must treat it as having no positions artifact.
    """
    run_dir = tmp_path / "runs" / RUN_ID
    (run_dir / "artifacts").mkdir(parents=True)
    target = tmp_path / "secret.csv"
    target.write_text("timestamp,LEAKED.SECRET\n2026-08-01T00:00:00,1.0\n", encoding="utf-8")
    (run_dir / "artifacts" / "positions.csv").symlink_to(target)
    client = _client(tmp_path, monkeypatch)

    response = client.get(f"/runs/{RUN_ID}/positions/sectors")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "run_id": RUN_ID,
        "symbols": {},
        "note": "no positions artifact",
    }
    assert target.read_text(encoding="utf-8").startswith("timestamp,LEAKED.SECRET")
