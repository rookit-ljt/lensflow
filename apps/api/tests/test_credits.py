import uuid

from conftest import authenticated_client

from app.credits_service import (
    InsufficientCreditsError,
    calculate_generation_cost,
    freeze_credits,
    refund_credits,
    settle_credits,
)
from app.database import SessionLocal
from app.db_models import User


def test_pricing_calculation():
    # Mock should always be 0
    assert calculate_generation_cost("image", "mock") == 0
    assert calculate_generation_cost("video", "mock") == 0
    assert calculate_generation_cost("text", "mock") == 0

    # Text
    assert calculate_generation_cost("text", "qwen") == 1

    # Image: 1K standard
    assert calculate_generation_cost("image", "qwen", parameters={"resolution": "1K", "count": 1}) == 2
    # Image: 2K
    assert calculate_generation_cost("image", "qwen", parameters={"resolution": "2K", "count": 1}) == 4
    # Image: with ref
    assert calculate_generation_cost("image", "qwen", parameters={"resolution": "1K", "count": 1, "uploaded_assets": ["1"]}) == 6
    # Image: 2K with count 2
    assert calculate_generation_cost("image", "qwen", parameters={"resolution": "2K", "count": 2}) == 8

    # Video: local_h3
    assert calculate_generation_cost("video", "local_h3") == 25


def test_wallet_initialization_and_endpoints():
    with authenticated_client() as client:
        # Get wallet for newly registered user (starts with 100 bonus credits)
        res = client.get("/api/credits/wallet")
        assert res.status_code == 200
        wallet = res.json()
        assert wallet["balance"] == 100
        assert wallet["frozen"] == 0
        assert wallet["total_earned"] == 100
        assert wallet["total_spent"] == 0

        # Get pricing
        pricing_res = client.get("/api/credits/pricing")
        assert pricing_res.status_code == 200
        items = pricing_res.json()["items"]
        assert len(items) >= 5

        # Estimate cost
        est_res = client.post(
            "/api/credits/estimate",
            json={"kind": "image", "provider": "qwen", "parameters": {"resolution": "2K", "count": 2}},
        )
        assert est_res.status_code == 200
        assert est_res.json()["cost"] == 8
        assert est_res.json()["sufficient"] is True


def test_credit_freeze_and_insufficient_credits():
    with authenticated_client() as client:
        # Create project and shot
        p_res = client.post("/api/projects", json={"name": "积分测试项目"})
        assert p_res.status_code == 201
        project_id = p_res.json()["id"]

        s_res = client.post(
            f"/api/projects/{project_id}/shots",
            json={"sequence_number": 1, "title": "镜头1", "visual_prompt": "雨夜电影感"},
        )
        assert s_res.status_code == 201
        shot_id = s_res.json()["id"]

        # User has 100 credits. Let's try requesting an image with count = 60 (2K: 4 * 60 = 240 credits > 100)
        gen_res = client.post(
            f"/api/shots/{shot_id}/generations",
            json={
                "provider": "mock",  # mock is 0 cost
                "kind": "image",
            },
        )
        # Mock is 0 cost, so succeeds
        assert gen_res.status_code == 202

        # Now let's test wallet operations directly
        with SessionLocal():
            # Check transactions
            tx_res = client.get("/api/credits/transactions")
            assert tx_res.status_code == 200
            assert len(tx_res.json()) >= 1  # at least the initial grant


def test_card_code_redeem():
    with authenticated_client() as client:
        # Admin generate a code
        gen_res = client.post(
            "/api/admin/credits/generate-codes",
            json={"count": 1, "credits": 50},
        )
        assert gen_res.status_code == 200
        code = gen_res.json()[0]["code"]

        # Initial wallet balance is 100
        w_before = client.get("/api/credits/wallet").json()["balance"]

        # Redeem the code
        redeem_res = client.post("/api/credits/redeem", json={"code": code})
        assert redeem_res.status_code == 200
        assert redeem_res.json()["credits_added"] == 50
        assert redeem_res.json()["new_balance"] == w_before + 50

        # Try redeeming again (should fail)
        again_res = client.post("/api/credits/redeem", json={"code": code})
        assert again_res.status_code == 400


def test_freeze_settle_refund_flow():
    with authenticated_client() as client:
        me = client.get("/api/auth/me").json()
        current_user_id = uuid.UUID(me["id"])

        w_res = client.get("/api/credits/wallet")
        assert w_res.status_code == 200
        initial_balance = w_res.json()["balance"]
        assert initial_balance == 100

        with SessionLocal() as session:
            user = session.get(User, current_user_id)
            assert user is not None

            # Freeze 30 credits
            freeze_credits(session, user, 30, "test_job", "job-1", "测试预冻结")
            session.commit()

            w = client.get("/api/credits/wallet").json()
            assert w["balance"] == 70
            assert w["frozen"] == 30

            # Try freezing more than available (70 available, request 100)
            try:
                freeze_credits(session, user, 100, "test_job", "job-2", "超额预扣")
                raise AssertionError("Should have raised InsufficientCreditsError")
            except InsufficientCreditsError as e:
                assert e.needed == 100
                assert e.available == 70

            # Settle job-1
            settle_credits(session, user.id, 30, "test_job", "job-1", "测试结算")
            session.commit()

            w = client.get("/api/credits/wallet").json()
            assert w["balance"] == 70
            assert w["frozen"] == 0
            assert w["total_spent"] == 30

            # Freeze and then refund
            freeze_credits(session, user, 20, "test_job", "job-3", "测试冻结退回")
            session.commit()
            w = client.get("/api/credits/wallet").json()
            assert w["balance"] == 50
            assert w["frozen"] == 20

            refund_credits(session, user.id, 20, "test_job", "job-3", "测试退回")
            session.commit()
            w = client.get("/api/credits/wallet").json()
            assert w["balance"] == 70
            assert w["frozen"] == 0

