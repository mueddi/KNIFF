"""Die Gesundheitsauskunft darf nie aus einem Zwischenspeicher kommen."""


def test_health_ohne_zwischenspeicher(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
