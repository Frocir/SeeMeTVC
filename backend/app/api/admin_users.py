from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_super_admin
from app.models import User
from app.schemas import AdminSetBalanceIn, AdminUserOut, BalanceEntryOut
from app.services.ledger import KIND_ADMIN, list_entries, record_entry

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=list[AdminUserOut])
async def list_users(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    result = await db.execute(select(User).order_by(User.id.asc()))
    return list(result.scalars().all())


@router.patch("/{user_id}/balance", response_model=AdminUserOut)
async def set_user_balance(
    user_id: int,
    body: AdminSetBalanceIn,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    delta = round(float(body.balance) - float(user.balance), 4)
    await record_entry(
        db,
        user,
        delta,
        kind=KIND_ADMIN,
        title="超管调整余额",
        ref_type="admin",
        ref_id=user.id,
    )
    user.balance = round(float(body.balance), 4)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}/ledger", response_model=list[BalanceEntryOut])
async def admin_user_ledger(
    user_id: int,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = 200,
) -> list[BalanceEntryOut]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    rows = await list_entries(db, user, limit=limit)
    return [BalanceEntryOut.model_validate(r) for r in rows]
