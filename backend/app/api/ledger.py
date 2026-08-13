from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import BalanceEntryOut
from app.services.ledger import list_entries

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/ledger", response_model=list[BalanceEntryOut])
async def my_ledger(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 200,
) -> list[BalanceEntryOut]:
    rows = await list_entries(db, user, limit=limit)
    return [BalanceEntryOut.model_validate(r) for r in rows]
