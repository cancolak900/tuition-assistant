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
