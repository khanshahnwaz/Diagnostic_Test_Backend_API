def pay(client, headers, booking_id, **extra):
    return client.post("/payments/", json={"booking_id": booking_id, **extra}, headers=headers)


def booking_status(client, headers, booking_id):
    return client.get(f"/bookings/{booking_id}", headers=headers).json()["status"]


def test_successful_payment_confirms_booking(client, booking, user_headers):
    res = pay(client, user_headers, booking["id"], outcome="SUCCESS")
    assert res.status_code == 201
    assert res.json()["status"] == "SUCCESS"
    assert res.json()["amount"] == "499.00"
    assert booking_status(client, user_headers, booking["id"]) == "CONFIRMED"


def test_failed_payment_marks_booking_failed(client, booking, user_headers):
    res = pay(client, user_headers, booking["id"], outcome="FAILED")
    assert res.json()["status"] == "FAILED"
    assert booking_status(client, user_headers, booking["id"]) == "FAILED"


def test_retry_after_failed_payment(client, booking, user_headers):
    pay(client, user_headers, booking["id"], outcome="FAILED")
    res = pay(client, user_headers, booking["id"], outcome="SUCCESS")
    assert res.status_code == 201
    assert booking_status(client, user_headers, booking["id"]) == "CONFIRMED"
    detail = client.get(f"/bookings/{booking['id']}", headers=user_headers).json()
    assert [p["status"] for p in detail["payments"]] == ["FAILED", "SUCCESS"]


def test_cannot_pay_twice_for_confirmed_booking(client, booking, user_headers):
    pay(client, user_headers, booking["id"], outcome="SUCCESS")
    assert pay(client, user_headers, booking["id"], outcome="SUCCESS").status_code == 409


def test_cannot_pay_cancelled_booking(client, booking, user_headers):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert pay(client, user_headers, booking["id"], outcome="SUCCESS").status_code == 409


def test_cannot_pay_someone_elses_booking(client, booking, other_headers):
    assert pay(client, other_headers, booking["id"], outcome="SUCCESS").status_code == 404


def test_payment_validation_and_auth(client, booking, user_headers):
    assert pay(client, user_headers, 9999).status_code == 404
    assert pay(client, user_headers, booking["id"], outcome="MAYBE").status_code == 422
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401
    assert client.post("/payments/", json={}, headers=user_headers).status_code == 422


def test_random_outcome_is_success_or_failed(client, booking, user_headers):
    res = pay(client, user_headers, booking["id"])
    assert res.json()["status"] in ("SUCCESS", "FAILED")


def test_async_payment_stays_pending_and_blocks_second_payment(client, booking, user_headers):
    res = pay(client, user_headers, booking["id"], async_mode=True)
    assert res.json()["status"] == "PENDING"
    assert booking_status(client, user_headers, booking["id"]) == "PENDING"
    assert pay(client, user_headers, booking["id"], outcome="SUCCESS").status_code == 409
