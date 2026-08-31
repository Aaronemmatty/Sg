import pytest
from fastapi import HTTPException

from sg_security.jwt_auth import CurrentUser, JWTAuthConfig, JWTAuthDependencies


@pytest.mark.asyncio
async def test_dev_stub_is_returned_when_public_key_missing():
    deps = JWTAuthDependencies(
        JWTAuthConfig(public_key_path="", is_production=False, dev_stub_roles=["trader"])
    )
    user = await deps.get_current_user_dependency(None)

    assert isinstance(user, CurrentUser)
    assert user.roles == ["trader"]
    assert user.sub == "dev-stub-user"


@pytest.mark.asyncio
async def test_production_mode_fails_closed_when_key_missing():
    deps = JWTAuthDependencies(JWTAuthConfig(public_key_path="", is_production=True))

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_current_user_dependency(None)

    assert exc_info.value.status_code == 503


def test_require_role_uses_dependency_pattern():
    deps = JWTAuthDependencies(JWTAuthConfig(public_key_path="", is_production=False))
    dependency = deps.require_role("trader")

    assert callable(dependency)
