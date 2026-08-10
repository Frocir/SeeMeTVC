from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_super_admin
from app.models import User
from app.schemas import AdminSetBalanceIn, AdminUserOut

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
    user.balance = body.balance
    await db.commit()
    await db.refresh(user)
    return user
