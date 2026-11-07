from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db

# Shared dependency: DB session (used when Postgres is wired up).
DbSession = Annotated[Session, Depends(get_db)]
