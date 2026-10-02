from datetime import datetime, timedelta, timezone

from tests.conftest import future_time


def test_create_booking(client, booking, seeded):
    assert booking["status"] == "PENDING"
    assert booking["amount"] == "499.00"
    assert booking["centre_id"] == seeded["centre_id"]


def test_booking_requires_auth(client, seeded):
    res = client.post("/bookings", json={**seeded, "appointment_at": future_time()})
    assert res.status_code == 401


def test_booking_in_the_past_rejected(client, user_headers, seeded):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    res = client.post("/bookings", json={**seeded, "appointment_at": past}, headers=user_headers)
    assert res.status_code == 422


def test_test_not_offered_by_centre(client, user_headers, seeded):
    res = client.post(
        "/bookings",
        json={"centre_id": seeded["centre_id"], "test_id": 9999, "appointment_at": future_time()},
        headers=user_headers,
    )
    assert res.status_code == 404


def test_duplicate_active_booking_rejected(client, user_headers, seeded):
    when = future_time()
    first = client.post("/bookings", json={**seeded, "appointment_at": when}, headers=user_headers)
    second = client.post("/bookings", json={**seeded, "appointment_at": when}, headers=user_headers)
    assert first.status_code == 201
    assert second.status_code == 409


def test_can_rebook_slot_after_cancel(client, user_headers, seeded):
    when = future_time()
    first = client.post("/bookings", json={**seeded, "appointment_at": when}, headers=user_headers).json()
    client.post(f"/bookings/{first['id']}/cancel", headers=user_headers)
    again = client.post("/bookings", json={**seeded, "appointment_at": when}, headers=user_headers)
    assert again.status_code == 201


def test_invalid_booking_id(client, user_headers):
    assert client.get("/bookings/9999", headers=user_headers).status_code == 404
    assert client.get("/bookings/abc", headers=user_headers).status_code == 422


def test_cannot_see_or_cancel_someone_elses_booking(client, booking, other_headers):
    assert client.get(f"/bookings/{booking['id']}", headers=other_headers).status_code == 404
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=other_headers).status_code == 404
    assert client.get("/bookings", headers=other_headers).json()["total"] == 0


def test_cancel_booking(client, booking, user_headers):
    res = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"
    again = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert again.status_code == 409


def test_list_and_status_filter(client, booking, user_headers):
    assert client.get("/bookings", headers=user_headers).json()["total"] == 1
    assert client.get("/bookings", params={"status": "CONFIRMED"}, headers=user_headers).json()["total"] == 0
    assert client.get("/bookings", params={"status": "BOGUS"}, headers=user_headers).status_code == 422


def test_booking_detail(client, booking, user_headers):
    res = client.get(f"/bookings/{booking['id']}", headers=user_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["centre"]["name"] == "Apollo Diagnostics"
    assert body["test"]["name"] == "CBC"
    assert body["payments"] == []


def test_amount_is_snapshot_of_price(client, booking, seeded, admin_headers, user_headers):
    client.post(
        f"/centres/{seeded['centre_id']}/tests", json={"name": "CBC", "price": "999.00"}, headers=admin_headers
    )
    res = client.get(f"/bookings/{booking['id']}", headers=user_headers)
    assert res.json()["amount"] == "499.00"
