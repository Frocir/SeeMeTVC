"""Append-only balance ledger. Every User.balance change should go through here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BalanceEntry, User

KIND_OPENING = "opening"
KIND_CHARGE = "charge"
KIND_REFUND = "refund"
KIND_ADMIN = "admin"
KIND_GRANT = "grant"


async def record_entry(
    db: AsyncSession,
    user: User,
    amount: float,
    *,
    kind: str,
    title: str,
    ref_type: str = "",
    ref_id: int | None = None,
    mutate: bool = True,
) -> BalanceEntry:
    amount = round(float(amount), 4)
    if mutate:
        user.balance = round(float(user.balance) + amount, 4)
    entry = BalanceEntry(
        user_id=user.id,
        amount=amount,
        balance_after=round(float(user.balance), 4),
        kind=kind,
        title=title[:200],
        ref_type=ref_type or "",
        ref_id=ref_id,
    )
    db.add(entry)
    return entry


async def ensure_opening_for_user(db: AsyncSession, user: User) -> bool:
    """If this user has no ledger rows yet, snapshot current balance as 期初."""
    existing = await db.execute(
        select(BalanceEntry.id).where(BalanceEntry.user_id == user.id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return False
    await record_entry(
        db,
        user,
        round(float(user.balance), 4),
        kind=KIND_OPENING,
        title="期初余额",
        mutate=False,
    )
    return True


async def ensure_opening_balances(db: AsyncSession) -> None:
    result = await db.execute(select(User))
    for user in result.scalars().all():
        await ensure_opening_for_user(db, user)


async def list_entries(
    db: AsyncSession,
    user: User,
    limit: int = 200,
) -> list[BalanceEntry]:
    if await ensure_opening_for_user(db, user):
        await db.commit()
        await db.refresh(user)
    limit = max(1, min(limit, 500))
    result = await db.execute(
        select(BalanceEntry)
        .where(BalanceEntry.user_id == user.id)
        .order_by(BalanceEntry.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
