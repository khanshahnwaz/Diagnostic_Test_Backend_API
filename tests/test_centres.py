def test_only_admin_can_create_centre(client, user_headers, admin_headers):
    payload = {"name": "Lal Path Labs", "location": "Ranchi"}
    assert client.post("/centres", json=payload).status_code == 401
    assert client.post("/centres", json=payload, headers=user_headers).status_code == 403
    assert client.post("/centres", json=payload, headers=admin_headers).status_code == 201


def test_duplicate_centre_rejected(client, admin_headers):
    payload = {"name": "Lal Path Labs", "location": "Ranchi"}
    client.post("/centres", json=payload, headers=admin_headers)
    assert client.post("/centres", json=payload, headers=admin_headers).status_code == 409


def test_add_test_and_list(client, seeded):
    res = client.get(f"/centres/{seeded['centre_id']}")
    assert res.status_code == 200
    offerings = res.json()["offerings"]
    assert len(offerings) == 1
    assert offerings[0]["test"]["name"] == "CBC"
    assert offerings[0]["price"] == "499.00"


def test_adding_same_test_updates_price(client, seeded, admin_headers):
    client.post(
        f"/centres/{seeded['centre_id']}/tests", json={"name": "cbc", "price": "550.00"}, headers=admin_headers
    )
    offerings = client.get(f"/centres/{seeded['centre_id']}").json()["offerings"]
    assert len(offerings) == 1
    assert offerings[0]["price"] == "550.00"
    assert len(client.get("/tests").json()["items"]) == 1


def test_invalid_price_rejected(client, seeded, admin_headers):
    for price in ["0", "-5", "abc"]:
        res = client.post(
            f"/centres/{seeded['centre_id']}/tests", json={"name": "X", "price": price}, headers=admin_headers
        )
        assert res.status_code == 422


def test_centre_not_found(client):
    assert client.get("/centres/9999").status_code == 404


def test_filter_and_pagination(client, admin_headers, seeded):
    for i in range(3):
        client.post("/centres", json={"name": f"Lab {i}", "location": "Delhi"}, headers=admin_headers)

    res = client.get("/centres", params={"location": "delhi"})
    assert res.json()["total"] == 3

    res = client.get("/centres", params={"page": 2, "page_size": 2})
    body = res.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2

    res = client.get("/centres", params={"test_id": seeded["test_id"]})
    assert res.json()["total"] == 1

    assert client.get("/centres", params={"page_size": 1000}).status_code == 422
