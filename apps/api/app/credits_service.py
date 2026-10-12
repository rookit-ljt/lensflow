import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import CreditCardCode, CreditTransaction, User, UserWallet


class InsufficientCreditsError(Exception):
    def __init__(self, needed: int, available: int):
        self.needed = needed
        self.available = available
        super().__init__(
            f"积分不足：本次操作需要 {needed} 积分，当前可用 {available} 积分。请充值或兑换积分后重试。"
        )


PRICING_CATALOG = [
    {
        "name": "文本生成 / 扩写",
        "category": "text",
        "cost": 1,
        "unit": "次",
        "description": "剧本、分镜叙事与提示词大模型扩写",
    },
    {
        "name": "标准图片生成 (1K)",
        "category": "image",
        "cost": 2,
        "unit": "张",
        "description": "标准清晰度文生图",
    },
    {
        "name": "高清图片生成 (2K)",
        "category": "image",
        "cost": 4,
        "unit": "张",
        "description": "2K 高清超清文生图",
    },
    {
        "name": "多模态参考图生成 / 重绘",
        "category": "image",
        "cost": 6,
        "unit": "张",
        "description": "包含 1~3 张参考图融合的多模态编辑",
    },
    {
        "name": "视频生成 (MiniMax H3)",
        "category": "video",
        "cost": 25,
        "unit": "次",
        "description": "高清 AI 视频生成 (首尾帧与运动控制)",
    },
    {
        "name": "Chat Agent 对话",
        "category": "agent",
        "cost": 1,
        "unit": "次",
        "description": "AI 创作助手多轮规划与方案构思",
    },
    {
        "name": "Mock 测试调用",
        "category": "mock",
        "cost": 0,
        "unit": "次",
        "description": "本地/无凭证编排测试 (免计费)",
    },
]


def calculate_generation_cost(
    kind: str,
    provider: str,
    model: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> int:
    """Calculate point cost dynamically based on media mode, provider, and parameters."""
    if provider == "mock":
        return 0

    params = parameters or {}
    if kind == "text":
        return 1

    if kind == "image":
        count = max(1, int(params.get("count", 1) or 1))
        resolution = str(params.get("resolution", "1K") or "1K")
        has_ref = bool(params.get("uploaded_assets") or params.get("context_source_node_ids"))
        base = 2
        if "2K" in resolution:
            base = 4
        if has_ref:
            base = max(base, 6)
        return base * count

    if kind == "video":
        return 25

    return 1


def calculate_agent_run_cost(provider: str) -> int:
    if provider == "mock":
        return 0
    return 1


def get_or_create_wallet(session: Session, user: User) -> UserWallet:
    wallet = session.scalar(select(UserWallet).where(UserWallet.user_id == user.id))
    if wallet is not None:
        return wallet

    # Local development user gets ample testing credits; registered users get starter bonus.
    is_local_user = user.email == "local@localhost.invalid"
    initial_credits = 9999 if is_local_user else 100

    wallet = UserWallet(
        user_id=user.id,
        balance=initial_credits,
        frozen=0,
        total_earned=initial_credits,
        total_spent=0,
    )
    session.add(wallet)
    session.flush()

    if initial_credits > 0:
        tx = CreditTransaction(
            user_id=user.id,
            wallet_id=wallet.id,
            amount=initial_credits,
            balance_after=initial_credits,
            type="grant",
            biz_type="gift",
            biz_id=str(user.id),
            idempotency_key=f"{user.id}:gift:initial",
            description="新用户注册/首次体验赠送积分",
        )
        session.add(tx)
        session.flush()

    return wallet


def freeze_credits(
    session: Session,
    user: User,
    amount: int,
    biz_type: str,
    biz_id: str,
    description: str,
) -> bool:
    if amount <= 0:
        return True

    wallet = get_or_create_wallet(session, user)
    if wallet.balance < amount:
        raise InsufficientCreditsError(needed=amount, available=wallet.balance)

    wallet.balance -= amount
    wallet.frozen += amount
    idempotency_key = f"{user.id}:{biz_type}:{biz_id}:freeze"

    existing_tx = session.scalar(
        select(CreditTransaction).where(CreditTransaction.idempotency_key == idempotency_key)
    )
    if existing_tx is not None:
        return True

    tx = CreditTransaction(
        user_id=user.id,
        wallet_id=wallet.id,
        amount=-amount,
        balance_after=wallet.balance,
        type="freeze",
        biz_type=biz_type,
        biz_id=biz_id,
        idempotency_key=idempotency_key,
        description=description,
    )
    session.add(tx)
    session.flush()
    return True


def settle_credits(
    session: Session,
    user_id: uuid.UUID,
    amount: int,
    biz_type: str,
    biz_id: str,
    description: str,
) -> bool:
    if amount <= 0:
        return True

    wallet = session.scalar(select(UserWallet).where(UserWallet.user_id == user_id))
    if wallet is None:
        return False

    wallet.frozen = max(0, wallet.frozen - amount)
    wallet.total_spent += amount
    idempotency_key = f"{user_id}:{biz_type}:{biz_id}:consume"

    existing_tx = session.scalar(
        select(CreditTransaction).where(CreditTransaction.idempotency_key == idempotency_key)
    )
    if existing_tx is not None:
        return True

    tx = CreditTransaction(
        user_id=user_id,
        wallet_id=wallet.id,
        amount=-amount,
        balance_after=wallet.balance,
        type="consume",
        biz_type=biz_type,
        biz_id=biz_id,
        idempotency_key=idempotency_key,
        description=description,
    )
    session.add(tx)
    session.flush()
    return True


def refund_credits(
    session: Session,
    user_id: uuid.UUID,
    amount: int,
    biz_type: str,
    biz_id: str,
    description: str,
) -> bool:
    if amount <= 0:
        return True

    wallet = session.scalar(select(UserWallet).where(UserWallet.user_id == user_id))
    if wallet is None:
        return False

    wallet.frozen = max(0, wallet.frozen - amount)
    wallet.balance += amount
    idempotency_key = f"{user_id}:{biz_type}:{biz_id}:refund"

    existing_tx = session.scalar(
        select(CreditTransaction).where(CreditTransaction.idempotency_key == idempotency_key)
    )
    if existing_tx is not None:
        return True

    tx = CreditTransaction(
        user_id=user_id,
        wallet_id=wallet.id,
        amount=amount,
        balance_after=wallet.balance,
        type="refund",
        biz_type=biz_type,
        biz_id=biz_id,
        idempotency_key=idempotency_key,
        description=description,
    )
    session.add(tx)
    session.flush()
    return True


def redeem_code(session: Session, user: User, code: str) -> int:
    clean_code = code.strip().upper()
    card = session.scalar(select(CreditCardCode).where(CreditCardCode.code == clean_code))
    if card is None:
        raise HTTPException(status_code=404, detail="兑换码无效或不存在，请检查后重新输入")
    if card.is_redeemed:
        raise HTTPException(status_code=400, detail="该兑换码已被使用过")
    if card.expires_at is not None:
        expires_at = card.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise HTTPException(status_code=400, detail="该兑换码已过期")

    wallet = get_or_create_wallet(session, user)
    wallet.balance += card.credits
    wallet.total_earned += card.credits

    card.is_redeemed = True
    card.redeemed_by_user_id = user.id
    card.redeemed_at = datetime.now(UTC)

    tx = CreditTransaction(
        user_id=user.id,
        wallet_id=wallet.id,
        amount=card.credits,
        balance_after=wallet.balance,
        type="redeem",
        biz_type="code",
        biz_id=str(card.id),
        idempotency_key=f"{user.id}:code:{card.id}:redeem",
        description=f"卡密兑换充值: {card.code} (+{card.credits} 积分)",
    )
    session.add(tx)
    session.flush()
    return card.credits


def grant_credits(
    session: Session,
    user_id: uuid.UUID,
    amount: int,
    description: str,
) -> UserWallet:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="指定用户不存在")

    wallet = get_or_create_wallet(session, user)
    wallet.balance += amount
    if amount > 0:
        wallet.total_earned += amount

    tx = CreditTransaction(
        user_id=user.id,
        wallet_id=wallet.id,
        amount=amount,
        balance_after=wallet.balance,
        type="grant",
        biz_type="admin",
        biz_id=str(uuid.uuid4()),
        idempotency_key=f"{user.id}:admin:{uuid.uuid4()}",
        description=description or "管理员调整积分",
    )
    session.add(tx)
    session.flush()
    return wallet


def generate_card_codes(
    session: Session,
    count: int = 5,
    credits: int = 100,
    expires_days: int = 30,
) -> list[CreditCardCode]:
    alphabet = string.ascii_uppercase + string.digits
    chars = [c for c in alphabet if c not in "01IO"]  # omit ambiguous characters
    created: list[CreditCardCode] = []
    expires_at = datetime.now(UTC) + timedelta(days=expires_days)

    for _ in range(count):
        part1 = "".join(secrets.choice(chars) for _ in range(4))
        part2 = "".join(secrets.choice(chars) for _ in range(4))
        code_str = f"LENS-{part1}-{part2}"
        card = CreditCardCode(
            code=code_str,
            credits=credits,
            expires_at=expires_at,
        )
        session.add(card)
        created.append(card)

    session.flush()
    return created
