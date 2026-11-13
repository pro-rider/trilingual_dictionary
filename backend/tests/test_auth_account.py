"""Profile column limits.

The deletion HTTP behaviour lives in `test_auth_phase2.py` now: re-authentication
was added after the first draft of this file, and the endpoint's response no
longer carries `already_absent`. Kept here are the pure policy rules, which do
not touch the network.
"""

from __future__ import annotations

import pytest

from app.services import profiles


@pytest.mark.parametrize("field", ["status", "username", "email", "user_id", "activated_at"])
def test_profile_update_refuses_identity_and_lifecycle_columns(field):
    with pytest.raises(profiles.ProfileWriteRejected) as exc:
        profiles.validate_profile_update({field: "x"})
    assert field in exc.value.columns


def test_profile_update_allows_only_presentation_columns():
    cleaned = profiles.validate_profile_update({"display_name": "  Surendra ", "locale": "ne"})
    assert cleaned == {"display_name": "Surendra", "locale": "ne"}


def test_username_is_normalised_and_shape_checked():
    assert profiles.normalize_username("  Anna ") == "anna"
    assert profiles.username_shape_errors("anna") == []
    assert profiles.username_shape_errors("Ann") != []
    assert profiles.username_shape_errors("an na") != []
    assert profiles.username_shape_errors("") != []


def test_email_is_normalised():
    assert profiles.normalize_email("  A@B.C ") == "a@b.c"
