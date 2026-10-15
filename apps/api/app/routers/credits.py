from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..auth import AdminUser, CurrentUser
from ..credits_service import (
    PRICING_CATALOG,
    calculate_generation_cost,
    generate_card_codes,
    get_or_create_wallet,
    grant_credits,
    redeem_code,
)
from ..db_models import CreditTransaction, UserWallet
from ..deps import DatabaseSession
from ..schemas import (
    CreditCardCodeRead,
    CreditEstimateRequest,
    CreditEstimateResponse,
    CreditGenerateCodesRequest,
    CreditGrantRequest,
    CreditPricingItem,
    CreditPricingRead,
    CreditRedeemRequest,
    CreditRedeemResponse,
    CreditTransactionRead,
    WalletRead,
)

router = APIRouter(tags=["credits"])


@router.get(
    "/api/credits/wallet",
    response_model=WalletRead,
)
def get_user_wallet(
    session: DatabaseSession,
    user: CurrentUser,
) -> UserWallet:
    return get_or_create_wallet(session, user)


@router.get(
    "/api/credits/pricing",
    response_model=CreditPricingRead,
)
def get_credits_pricing() -> CreditPricingRead:
    return CreditPricingRead(items=[CreditPricingItem(**item) for item in PRICING_CATALOG])


@router.post(
    "/api/credits/estimate",
    response_model=CreditEstimateResponse,
)
def estimate_credits_cost(
    payload: CreditEstimateRequest,
    session: DatabaseSession,
    user: CurrentUser,
) -> CreditEstimateResponse:
    cost = calculate_generation_cost(
        kind=payload.kind,
        provider=payload.provider,
        model=payload.model,
        parameters=payload.parameters,
    )
    wallet = get_or_create_wallet(session, user)
    return CreditEstimateResponse(
        cost=cost,
        balance=wallet.balance,
        sufficient=wallet.balance >= cost,
    )


@router.get(
    "/api/credits/transactions",
    response_model=list[CreditTransactionRead],
)
def list_credit_transactions(
    session: DatabaseSession,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[CreditTransaction]:
    get_or_create_wallet(session, user)
    session.commit()
    statement = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement))


@router.post(
    "/api/credits/redeem",
    response_model=CreditRedeemResponse,
)
def redeem_credit_code(
    payload: CreditRedeemRequest,
    session: DatabaseSession,
    user: CurrentUser,
) -> CreditRedeemResponse:
    credits_added = redeem_code(session, user, payload.code)
    wallet = get_or_create_wallet(session, user)
    session.commit()
    return CreditRedeemResponse(
        credits_added=credits_added,
        new_balance=wallet.balance,
    )


@router.post(
    "/api/admin/credits/grant",
    response_model=WalletRead,
)
def admin_grant_credits(
    payload: CreditGrantRequest,
    session: DatabaseSession,
    user: AdminUser,
) -> UserWallet:
    wallet = grant_credits(session, payload.user_id, payload.amount, payload.description)
    session.commit()
    return wallet


@router.post(
    "/api/admin/credits/generate-codes",
    response_model=list[CreditCardCodeRead],
)
def admin_generate_card_codes(
    payload: CreditGenerateCodesRequest,
    session: DatabaseSession,
    user: AdminUser,
) -> list[CreditCardCodeRead]:
    cards = generate_card_codes(session, payload.count, payload.credits, payload.expires_days)
    session.commit()
    return [CreditCardCodeRead.model_validate(card) for card in cards]
