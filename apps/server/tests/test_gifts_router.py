"""routers/gifts.py — docs/phases/PHASE-9-personal-goals.md §4. Every label/
price here is a clearly synthetic placeholder (docs/PRIVATE.md: real
occasion names/prices must never appear in a fixture).
"""
from __future__ import annotations

from tests.conftest import auth_headers, make_user


def test_gifts_requires_auth(client):
    assert client.get("/api/gifts/occasions").status_code == 401


def test_occasions_empty_before_any_created(client):
    user_id = make_user()
    res = client.get("/api/gifts/occasions", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"occasions": []}


def test_create_occasion_no_limit_given_reports_no_limit_set(client):
    user_id = make_user()
    res = client.post("/api/gifts/occasions", headers=auth_headers(user_id), json={"label": "Occasion A"})
    assert res.status_code == 201
    occasion = res.json()["occasion"]
    assert occasion["limit_minor"] is None
    assert occasion["verdict"] == "no_limit_set"
    assert occasion["items"] == []


def test_occasion_items_roll_up_against_the_limit(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    occasion_id = client.post(
        "/api/gifts/occasions", headers=headers, json={"label": "Occasion A", "limit_minor": 10_000}
    ).json()["occasion"]["id"]

    client.post(f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item", "price_minor": 4_000})
    added = client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item two", "price_minor": 3_000}
    ).json()["occasion"]

    assert added["spent_minor"] == 7_000
    assert added["remaining_minor"] == 3_000
    assert added["verdict"] == "under_limit"
    assert len(added["items"]) == 2


def test_occasion_over_limit_is_calm_information(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    occasion_id = client.post(
        "/api/gifts/occasions", headers=headers, json={"label": "Occasion A", "limit_minor": 5_000}
    ).json()["occasion"]["id"]
    over = client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item", "price_minor": 8_000}
    ).json()["occasion"]
    assert over["verdict"] == "over_limit"
    assert over["remaining_minor"] == -3_000
    # calm copy discipline: no guilt words anywhere in what the API returns
    assert "!" not in str(over)


def test_item_bought_toggle_and_delete(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    occasion_id = client.post("/api/gifts/occasions", headers=headers, json={"label": "Occasion A"}).json()["occasion"]["id"]
    item_id = client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item", "price_minor": 2_500}
    ).json()["occasion"]["items"][0]["id"]

    patched = client.patch(
        f"/api/gifts/items/{item_id}", headers=headers, json={"bought": True, "bought_date": "2026-08-01"}
    ).json()["occasion"]
    item = next(i for i in patched["items"] if i["id"] == item_id)
    assert item["bought"] is True
    assert item["bought_date"] == "2026-08-01"

    deleted = client.delete(f"/api/gifts/items/{item_id}", headers=headers)
    assert deleted.status_code == 200
    after = client.get("/api/gifts/occasions", headers=headers).json()["occasions"][0]
    assert after["items"] == []


def test_item_affordability_reads_the_occasions_remaining_budget(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    occasion_id = client.post(
        "/api/gifts/occasions", headers=headers, json={"label": "Occasion A", "limit_minor": 10_000}
    ).json()["occasion"]["id"]
    item_id = client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item", "price_minor": 3_000}
    ).json()["occasion"]["items"][0]["id"]

    result = client.get(f"/api/gifts/items/{item_id}/affordability", headers=headers).json()
    # remaining budget excluding this item's own price = 10,000 (no other items)
    assert result["verdict"] == "fits_now"


def test_occasion_and_item_404_for_another_users_data(client):
    owner = make_user(email="owner@example.com", mishka_id=1)
    intruder = make_user(email="intruder@example.com", mishka_id=2)
    occasion_id = client.post(
        "/api/gifts/occasions", headers=auth_headers(owner), json={"label": "Occasion A"}
    ).json()["occasion"]["id"]

    assert client.patch(
        f"/api/gifts/occasions/{occasion_id}", headers=auth_headers(intruder), json={"label": "hijacked"}
    ).status_code == 404
    assert client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=auth_headers(intruder), json={"label": "x", "price_minor": 100}
    ).status_code == 404


def test_negative_limit_and_non_positive_price_rejected(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    assert client.post("/api/gifts/occasions", headers=headers, json={"label": "Occasion A", "limit_minor": -1}).status_code == 400
    occasion_id = client.post("/api/gifts/occasions", headers=headers, json={"label": "Occasion A"}).json()["occasion"]["id"]
    assert client.post(
        f"/api/gifts/occasions/{occasion_id}/items", headers=headers, json={"label": "gift item", "price_minor": 0}
    ).status_code == 400
