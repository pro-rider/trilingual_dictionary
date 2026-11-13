from __future__ import annotations

from pydantic import Field, StrictBool, StrictStr, field_validator

from app.core.validation import StrictModel


class EmailField(StrictModel):
    email: StrictStr = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _shape(cls, value: str) -> str:
        value = value.strip()
        if value.count("@") != 1:
            raise ValueError("enter a valid email address")
        local, _, domain = value.partition("@")
        if not local or "." not in domain or domain.startswith("."):
            raise ValueError("enter a valid email address")
        return value.lower()


class RegisterStartRequest(EmailField):
    """Always answers the same way, whether or not the address is known."""


class RegisterVerifyRequest(EmailField):
    code: StrictStr = Field(min_length=6, max_length=6)


class RegisterVerifyResponse(StrictModel):
    signup_token: str
    expires_in: int


class RegisterCompleteRequest(StrictModel):
    signup_token: StrictStr = Field(min_length=16, max_length=128)
    username: StrictStr = Field(min_length=3, max_length=20)
    password: StrictStr = Field(min_length=8, max_length=128)


class LoginRequest(StrictModel):
    # Username or email. Never echoed in an error.
    identifier: StrictStr = Field(min_length=3, max_length=254)
    password: StrictStr = Field(min_length=1, max_length=128)
    device_id: StrictStr | None = Field(default=None, max_length=64)


class TokenPair(StrictModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ProfileResponse(StrictModel):
    user_id: str
    email: str
    username: str | None
    status: str
    nepali_enabled: bool = True
    display_name: str | None = None
    locale: str | None = None


class ProfileUpdateRequest(StrictModel):
    """Only presentation fields. ``status`` is rejected as an unknown field."""

    display_name: StrictStr | None = Field(default=None, max_length=60)
    locale: StrictStr | None = Field(default=None, max_length=16)


class AccountDeleteRequest(StrictModel):
    confirm: StrictBool
    # One of the two proves possession. A stolen access token alone is not
    # enough to destroy the account.
    password: StrictStr | None = Field(default=None, max_length=128)
    code: StrictStr | None = Field(default=None, min_length=6, max_length=6)


class AccountDeleteResponse(StrictModel):
    deleted: bool
    already_absent: bool = False


class UsernameAvailability(StrictModel):
    available: bool


class MessageResponse(StrictModel):
    detail: str
