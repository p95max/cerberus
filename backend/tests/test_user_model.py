import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_custom_user_model_is_active() -> None:
    user = get_user_model().objects.create_user(username="operator")

    assert user.get_username() == "operator"
