"""Service skeleton: health probes, /api/v1 prefix, Swagger and the common error format."""

UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


def test_liveness_ok(make_client):
    """Liveness answers without touching the database."""
    res = make_client(UNREACHABLE_DB).get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readiness_ok_with_real_postgres(client):
    """Readiness runs SELECT 1 against a real PostgreSQL 16 container."""
    res = client.get("/api/v1/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}


def test_readiness_db_down_uses_error_format(make_client):
    """Database unreachable -> 503 with the common error body."""
    res = make_client(UNREACHABLE_DB).get("/api/v1/health/ready")
    assert res.status_code == 503
    assert res.json() == {"error": {"code": "DATABASE_UNAVAILABLE", "message": "The database is not reachable.", "details": None}}


def test_unknown_route_uses_error_format(make_client):
    """Unknown paths return 404 in the common error format, not FastAPI's default {"detail": ...}."""
    res = make_client(UNREACHABLE_DB).get("/api/v1/does-not-exist")
    assert res.status_code == 404
    body = res.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "NOT_FOUND"


def test_wrong_method_uses_error_format(make_client):
    res = make_client(UNREACHABLE_DB).post("/api/v1/health")
    assert res.status_code == 405
    assert res.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_routes_are_versioned_and_swagger_is_served(make_client):
    c = make_client(UNREACHABLE_DB)
    assert c.get("/health").status_code == 404  # nothing outside /api/v1
    assert c.get("/api/v1/docs").status_code == 200
    spec = c.get("/api/v1/openapi.json").json()
    assert all(path.startswith("/api/v1/") for path in spec["paths"])


def test_unexpected_error_returns_500_in_error_format(monkeypatch):
    """A crash inside a route never leaks a stack trace; the body uses the common error format."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    res = TestClient(app, raise_server_exceptions=False).get("/api/v1/boom")
    assert res.status_code == 500
    assert res.json() == {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred.", "details": None}}
    assert "secret" not in res.text


def test_request_id_is_echoed_and_logged(make_client, caplog):
    """Correlation id: the gateway's X-Request-ID is returned and written to the access log."""
    import logging

    c = make_client(UNREACHABLE_DB)
    with caplog.at_level(logging.INFO, logger="tuition-api.access"):
        res = c.get("/api/v1/health", headers={"X-Request-ID": "req-123"})
    assert res.headers["X-Request-ID"] == "req-123"
    assert any("request_id=req-123" in r.getMessage() and "status=200" in r.getMessage() for r in caplog.records)
    assert len(c.get("/api/v1/health").headers["X-Request-ID"]) == 32  # generated when missing
