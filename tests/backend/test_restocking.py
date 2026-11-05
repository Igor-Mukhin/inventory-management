"""
Tests for restocking API endpoints.
"""
from datetime import date, datetime


class TestRestockRecommendationEndpoints:
    """Test suite for restock recommendations."""

    def test_recommendations_return_list(self, client):
        """Test that recommendations return a list of well-formed rows."""
        response = client.get("/api/restock/recommendations?budget=100000")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for row in data:
            for field in ("sku", "name", "category", "warehouse", "quantity_on_hand",
                          "forecasted_demand", "shortfall", "unit_cost", "line_cost",
                          "urgency", "lead_time_days"):
                assert field in row, f"missing field {field}"
            assert row["shortfall"] > 0
            assert row["urgency"] > 0  # shortfall is positive, so the ratio is too

    def test_recommendations_zero_budget_returns_nothing(self, client):
        """Test that a zero budget recommends no lines."""
        response = client.get("/api/restock/recommendations?budget=0")
        assert response.status_code == 200
        assert response.json() == []

    def test_recommendations_total_never_exceeds_budget(self, client):
        """Test that the funded total stays within the budget for several budgets."""
        for budget in (1000, 5000, 25000, 100000):
            data = client.get(f"/api/restock/recommendations?budget={budget}").json()
            total = sum(row["line_cost"] for row in data)
            assert total <= budget + 0.005, f"budget {budget} exceeded: {total}"

    def test_recommendations_sorted_by_urgency(self, client):
        """Test that recommendations are ranked most urgent first."""
        data = client.get("/api/restock/recommendations?budget=500000").json()
        urgencies = [row["urgency"] for row in data]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_recommendations_greedy_skips_expensive_item(self, client):
        """Test that an item too expensive for the remaining budget is skipped, not the whole list."""
        # At 5000 the top-ranked FLT-405 (6370) and WDG-001 (11475) do not fit,
        # but cheaper lower-ranked items still do.
        data = client.get("/api/restock/recommendations?budget=5000").json()
        skus = [row["sku"] for row in data]
        assert "FLT-405" not in skus
        assert "WDG-001" not in skus
        assert skus == ["GSK-203", "SNR-420", "BRG-102"]

    def test_recommendations_exclude_skus_without_inventory(self, client):
        """Test that forecast SKUs with no inventory record are not recommended."""
        inventory_skus = {item["sku"] for item in client.get("/api/inventory").json()}
        data = client.get("/api/restock/recommendations?budget=500000").json()
        for row in data:
            assert row["sku"] in inventory_skus

    def test_recommendations_negative_budget_rejected(self, client):
        """Test that a negative budget is rejected."""
        response = client.get("/api/restock/recommendations?budget=-1")
        assert response.status_code == 400

    def test_recommendations_missing_budget_rejected(self, client):
        """Test that the budget parameter is required."""
        response = client.get("/api/restock/recommendations")
        assert response.status_code == 422


class TestRestockOrderEndpoints:
    """Test suite for submitting and listing restock orders."""

    def test_place_order_computes_costs_and_delivery(self, client):
        """Test that a submitted order computes costs and expected delivery from inventory."""
        response = client.post("/api/restock/orders", json={
            "lines": [
                {"sku": "VLV-506", "quantity": 61},
                {"sku": "CTL-330", "quantity": 56},
            ]
        })
        assert response.status_code == 201

        order = response.json()
        assert order["item_count"] == 2
        assert order["total_cost"] == 3538.0 + 4984.0

        # Lead time is the slowest line (CTL-330 is 21 days, VLV-506 is 21 days).
        assert order["lead_time_days"] == 21
        submitted = datetime.fromisoformat(order["submitted_at"]).date()
        expected = date.fromisoformat(order["expected_delivery"])
        assert (expected - submitted).days == order["lead_time_days"]

    def test_place_order_ignores_client_supplied_cost(self, client):
        """Test that the server recomputes line costs rather than trusting the client."""
        response = client.post("/api/restock/orders", json={
            "lines": [{"sku": "PSU-501", "quantity": 2}]
        })
        assert response.status_code == 201
        line = response.json()["lines"][0]
        assert line["unit_cost"] == 18.99
        assert line["line_cost"] == round(2 * 18.99, 2)

    def test_place_order_empty_lines_rejected(self, client):
        """Test that an order with no lines is rejected."""
        response = client.post("/api/restock/orders", json={"lines": []})
        assert response.status_code == 400

    def test_place_order_unknown_sku_rejected(self, client):
        """Test that an unknown SKU returns 404."""
        response = client.post("/api/restock/orders", json={
            "lines": [{"sku": "NOPE-999", "quantity": 1}]
        })
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_place_order_non_positive_quantity_rejected(self, client):
        """Test that zero or negative quantities are rejected."""
        response = client.post("/api/restock/orders", json={
            "lines": [{"sku": "VLV-506", "quantity": 0}]
        })
        assert response.status_code == 400

    def test_get_orders_includes_submitted_order_newest_first(self, client):
        """Test that a submitted order appears in the list, newest first."""
        posted = client.post("/api/restock/orders", json={
            "lines": [{"sku": "SNR-420", "quantity": 10}]
        }).json()

        listing = client.get("/api/restock/orders")
        assert listing.status_code == 200
        orders = listing.json()
        assert orders[0]["id"] == posted["id"]
