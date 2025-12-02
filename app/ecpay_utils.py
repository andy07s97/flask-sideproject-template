# app/ecpay_utils.py
"""
Minimal/public version of ECPay helper utilities.

This file keeps:
  - Subscription plan definitions (PLANS)
  - Function names and parameters (public interface)

But it strips out:
  - Actual ECPay SDK calls
  - Database models and side effects
  - CheckMacValue implementation details

So it is safe to put on GitHub. If you want this to work in
your own project, you must implement the bodies yourself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Tuple, Dict, Any

# -----------------------------------------------------------------------------
# Plan definitions (public config)
# -----------------------------------------------------------------------------

# In your real project, these might come from models or a settings file.
PLAN_MONTH = "PLAN_MONTH"
PLAN_YEAR = "PLAN_YEAR"

PLANS: Dict[str, Dict[str, Any]] = {
    PLAN_MONTH: {
        "months": 1,
        "amount": 129,
        "item_name": "YouTube Transcript+AI 月訂閱 (1 個月)",
        "desc": "無限制取用轉錄稿及所有AI服務（公平使用）",
    },
    PLAN_YEAR: {
        "months": 12,
        "amount": 1188,  # 99 * 12
        "item_name": "YouTube Transcript+AI 年訂閱 (12 個月)",
        "desc": "無限制取用轉錄稿及所有AI服務（公平使用）",
    },
}


# -----------------------------------------------------------------------------
# Helper for MerchantTradeNo
# -----------------------------------------------------------------------------

def new_merchant_trade_no(prefix: str = "YTT") -> str:
    """
    Generate a MerchantTradeNo string.

    NOTE: This is kept functional because it doesn't touch secrets or DB.
    """
    # 10 chars of timestamp
    tail = datetime.utcnow().strftime("%m%d%H%M%S")
    # 8 chars of random hex
    short = uuid.uuid4().hex[:8].upper()
    raw = f"{prefix}{tail}{short}"  # typically 21 chars
    return raw[:20]                 # hard cap at 20 chars


# -----------------------------------------------------------------------------
# CheckMacValue helpers (interface only)
# -----------------------------------------------------------------------------

def build_check_mac(params: dict, hash_key: str, hash_iv: str) -> str:
    """
    Build CheckMacValue per ECPay rules.

    PUBLIC INTERFACE ONLY: implementation removed in public template.
    Implement this yourself if you need real ECPay integration.
    """
    raise NotImplementedError(
        "build_check_mac is not implemented in the public GitHub version. "
        "Please implement ECPay CheckMacValue calculation yourself."
    )


def verify_check_mac(form_data, hash_key: str, hash_iv: str) -> bool:
    """
    Verify CheckMacValue from ECPay callback.

    form_data: ImmutableMultiDict or dict-like (Flask request.form)

    PUBLIC INTERFACE ONLY: implementation removed.
    """
    raise NotImplementedError(
        "verify_check_mac is not implemented in the public GitHub version. "
        "Please implement ECPay CheckMacValue verification yourself."
    )


# -----------------------------------------------------------------------------
# Checkout params (interface only)
# -----------------------------------------------------------------------------

def build_checkout_params(user, plan_code: str):
    """
    Create payment record and build signed params for AIO checkout.

    Parameters
    ----------
    user : your User model instance
        The currently logged-in user.
    plan_code : str
        One of PLAN_MONTH or PLAN_YEAR.

    Returns
    -------
