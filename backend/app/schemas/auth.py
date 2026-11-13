from pydantic import BaseModel, ConfigDict, StrictBool


class AccountDeleteRequest(BaseModel):
    """Deletion is irreversible, so it takes an explicit boolean.

    A bare DELETE from a stale script or a mis-wired client should not remove an
    account; the body makes the intent part of the request.
    """

    model_config = ConfigDict(extra="forbid")

    confirm: StrictBool


class AccountDeleteResponse(BaseModel):
    deleted: bool
    already_absent: bool = False
