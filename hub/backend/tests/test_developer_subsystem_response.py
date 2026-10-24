from datetime import datetime

from app.routers.developer import SubsystemResponse


def test_developer_subsystem_response_exposes_owner_manageable_configuration():
    response = SubsystemResponse(
        id="sub-1",
        name="Library",
        description=None,
        client_id="client-1",
        status="active",
        scope=["openid"],
        access_policy="role",
        access_policy_config={"roles": ["student"]},
        api_key_prefix="rk_live_123",
        access_revoke_webhook_url="https://library.example/internal/access-revoked",
        previous_secret_expires_at=datetime(2026, 10, 25),
        created_at=datetime(2026, 10, 24),
    ).model_dump()

    assert response["access_policy"] == "role"
    assert response["access_policy_config"] == {"roles": ["student"]}
    assert response["api_key_prefix"] == "rk_live_123"
    assert response["access_revoke_webhook_url"].startswith("https://")
    assert response["previous_secret_expires_at"] == datetime(2026, 10, 25)
