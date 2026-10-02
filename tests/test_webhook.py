from tests.conftest import send_webhook


def pending_payment(client, headers, booking_id):
    res = client.post("/payments/", json={"booking_id": booking_id, "async_mode": True}, headers=headers)
    assert res.status_code == 201
    return res.json()


def payment_count(client, headers, booking_id):
    return len(client.get(f"/bookings/{booking_id}", headers=headers).json()["payments"])


def test_webhook_confirms_booking(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    res = send_webhook(
        client, {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "SUCCESS"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "processed"
    detail = client.get(f"/bookings/{booking['id']}", headers=user_headers).json()
    assert detail["status"] == "CONFIRMED"
    assert detail["payments"][0]["status"] == "SUCCESS"


def test_webhook_failure_marks_booking_failed(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    send_webhook(client, {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "FAILED"})
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "FAILED"


def test_same_event_twice_is_idempotent(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    payload = {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "SUCCESS"}

    first = send_webhook(client, payload)
    second = send_webhook(client, payload)
    third = send_webhook(client, payload)

    assert first.json()["status"] == "processed"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert third.json()["status"] == "duplicate"
    assert payment_count(client, user_headers, booking["id"]) == 1
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "CONFIRMED"


def test_new_event_for_settled_payment_is_ignored(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    ref = payment["reference"]
    send_webhook(client, {"event_id": "evt_1", "payment_reference": ref, "status": "SUCCESS"})

    # a different event claiming the opposite must not flip the booking back
    res = send_webhook(client, {"event_id": "evt_2", "payment_reference": ref, "status": "FAILED"})
    assert res.json()["status"] == "ignored"
    detail = client.get(f"/bookings/{booking['id']}", headers=user_headers).json()
    assert detail["status"] == "CONFIRMED"
    assert detail["payments"][0]["status"] == "SUCCESS"


def test_webhook_after_sync_payment_changes_nothing(client, booking, user_headers):
    payment = client.post(
        "/payments/", json={"booking_id": booking["id"], "outcome": "SUCCESS"}, headers=user_headers
    ).json()
    res = send_webhook(
        client, {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "SUCCESS"}
    )
    assert res.json()["status"] == "ignored"
    assert payment_count(client, user_headers, booking["id"]) == 1


def test_success_webhook_does_not_revive_cancelled_booking(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    send_webhook(client, {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "SUCCESS"})
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "CANCELLED"


def test_unknown_payment_reference(client):
    res = send_webhook(client, {"event_id": "evt_1", "payment_reference": "pay_nope", "status": "SUCCESS"})
    assert res.status_code == 404
    # nothing was recorded, so the same event can be retried once the payment exists
    res = send_webhook(client, {"event_id": "evt_1", "payment_reference": "pay_nope", "status": "SUCCESS"})
    assert res.status_code == 404


def test_bad_signature_rejected(client, booking, user_headers):
    payment = pending_payment(client, user_headers, booking["id"])
    payload = {"event_id": "evt_1", "payment_reference": payment["reference"], "status": "SUCCESS"}
    assert send_webhook(client, payload, signature="deadbeef").status_code == 401
    assert client.post("/payments/webhook/", json=payload).status_code == 401
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "PENDING"


def test_invalid_payloads(client):
    assert send_webhook(client, {"event_id": "evt_1"}).status_code == 422
    bad_status = {"event_id": "evt_1", "payment_reference": "pay_x", "status": "MAYBE"}
    assert send_webhook(client, bad_status).status_code == 422
