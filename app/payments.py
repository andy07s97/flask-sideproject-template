# /opt/ytt/app/payments.py
from datetime import datetime, timezone
from flask import (
    Blueprint,
    request,
    current_app,
    jsonify,
    Response,
    render_template,
)
from flask_login import current_user, login_required

from .models import db, User, Payment
from .ecpay_utils import verify_check_mac, build_checkout_params
from .ecpay_utils import PLAN_MONTH, PLAN_YEAR


# All ECPay-related endpoints share this blueprint.
# URL prefix /ecpay keeps your existing ReturnURL as /ecpay/return
payments_bp = Blueprint("payments", __name__, url_prefix="/ecpay")


def _plan_from_order(order: Payment) -> str:
    """
    Helper: decide which subscription plan to apply based on the Order row.
    You already store plan_code in the DB, so just trust that.
    """
    return order.plan_code


# -------------------------------------------------------------------
# 1) Server-created order: user clicks "subscribe" -> /ecpay/create
# -------------------------------------------------------------------
@payments_bp.route("/create", methods=["POST"])
@login_required
def create_payment():
    """
    Create an ECPay order on the server side and redirect the user to ECPay.

    Frontend example:
        <form action="/ecpay/create" method="post">
          <input type="hidden" name="plan" value="A">  <!-- or B -->
          <button type="submit">訂閱</button>
        </form>

    Expects:
      - form field `plan` = "A" or "B"
    Uses:
      - build_checkout_params(current_user, plan)
        which must:
          * create an Order row in your DB with merchant_trade_no, plan_code, user_id, trade_amt...
          * return (signed_params_dict, order_instance)
    Renders:
      - ecpay_redirect.html with an auto-submitting POST form to ECPay.
    """
    # Validate plan
    plan = request.form.get("plan")
    if plan not in (PLAN_MONTH, PLAN_YEAR):
        return Response("Invalid plan", status=400, mimetype="text/plain")

    # This helper should:
    #   1. generate a unique MerchantTradeNo
    #   2. create a Payment row in DB (status=PENDING, plan_code=plan, user_id=current_user.id)
    #   3. call ECPay SDK's create_order(...) and return signed params
    signed, order = build_checkout_params(current_user, plan)

    # ECPAY_SERVICE_URL should be configured in your app config
    epay_url = current_app.config.get(
        "ECPAY_SERVICE_URL",
        "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5",  # default fallback
    )

    return render_template("ecpay_redirect.html", signed=signed, epay_url=epay_url)


# -------------------------------------------------------------------
# 2) ReturnURL: ECPay server -> your server (POST form-data)
# -------------------------------------------------------------------
@payments_bp.route("/return", methods=["POST"])
def ecpay_return():
    """
    Step1+2: ECPay Server POST hits here. We:
      - parse form data
      - verify CheckMacValue immediately
      - update Order row with raw fields
      - mark as PAID if RtnCode==1
      - extend user's subscription
      - reply '1|OK' (plain text)

    This endpoint path should match the ReturnURL that you configured in ECPay:
        https://your-domain/ecpay/return
    """
    form = request.form or {}
    app = current_app

    merchant_trade_no = form.get("MerchantTradeNo")
    if not merchant_trade_no:
        # Still respond 200/OK, but not "1|OK" (ECPay might retry). You log for inspection.
        app.logger.error("ECPay ReturnURL missing MerchantTradeNo")
        return Response("0|Missing MerchantTradeNo", mimetype="text/plain")

    # Find order
    order = Payment.query.filter_by(merchant_trade_no=merchant_trade_no).first()
    if not order:
        current_app.logger.error("ECPay ReturnURL unknown MerchantTradeNo=%s", merchant_trade_no)
        return Response("0|Unknown MerchantTradeNo", mimetype="text/plain")

    # Idempotency: if already processed as PAID we still say 1|OK
    if order.trade_status == "PAID":
        return Response("1|OK", mimetype="text/plain")

    # Verify CheckMacValue
    hash_key = app.config.get("ECPAY_HASH_KEY", "")
    hash_iv = app.config.get("ECPAY_HASH_IV", "")
    ok_mac = False
    try:
        ok_mac = verify_check_mac(form, hash_key, hash_iv)
    except Exception as e:
        app.logger.exception("CheckMac verification crashed: %s", e)

    # Store raw fields (regardless of MAC) for audit
    try:
        order.rtn_code = int(form.get("RtnCode") or 0)
    except Exception:
        order.rtn_code = 0
    order.rtn_msg = form.get("RtnMsg")
    try:
        # Keep previous trade_amt if parsing fails
        order.trade_amt = int(form.get("TradeAmt")) if form.get("TradeAmt") else order.trade_amt
    except Exception:
        pass

    order.trade_no = form.get("TradeNo")
    order.payment_type = form.get("PaymentType")

    fee = form.get("PaymentTypeChargeFee")
    if fee and fee.isdigit():
        order.payment_type_fee = int(fee)
    else:
        order.payment_type_fee = None

    order.payment_date_raw = form.get("PaymentDate")
    order.check_mac_value = form.get("CheckMacValue")
    order.simulate_paid = (str(form.get("SimulatePaid") or "0") == "1")
    db.session.add(order)

    # If MAC invalid, mark FAILED but still respond 1|OK so ECPay won't spam retries.
    # You can rely on Step3 reconciliation or manual inspection to catch tampering.
    if not ok_mac:
        order.trade_status = "FAILED"
        db.session.commit()
        app.logger.error("ECPay ReturnURL CheckMac mismatch for %s", merchant_trade_no)
        return Response("1|OK", mimetype="text/plain")

    # MAC ok → if transaction success, mark PAID and grant subscription
    if order.rtn_code == 1:
        try:
            order.mark_paid()  # your Order model should set paid_at based on payment_date_raw

            plan = _plan_from_order(order)
            if order.user_id:
                user = User.query.get(order.user_id)
                if user:
                    # You defined activate_from_plan_code(plan)
                    user.activate_from_plan_code(plan)
                    db.session.add(user)

            order.verified = True  # We treat ReturnURL+MAC as good; Step3 can re-check.
            order.trade_status = "PAID"
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to grant subscription for %s", merchant_trade_no)
            # Still 1|OK so ECPay will not hammer us; you will fix via Step3 job.
            return Response("1|OK", mimetype="text/plain")
    else:
        order.trade_status = "FAILED"
        db.session.commit()

    # Step2 response (plain text)
    return Response("1|OK", mimetype="text/plain")


# -------------------------------------------------------------------
# 3) Optional: manual reconciliation endpoint for specific orders
# -------------------------------------------------------------------
@payments_bp.route("/reconcile/<merchant_trade_no>", methods=["POST"])
def reconcile_one(merchant_trade_no):
    """
    Step3 example endpoint you can call from cron or manually.
    Recommended:
      - Make sure your local DB state is consistent with ECPay's result
      - Optionally call ECPay QueryTradeInfo API here (not shown) if needed

    Here we only:
      - If ReturnURL recorded success but status != PAID, mark PAID.
      - If user not upgraded but should be, activate subscription now.
    """
    order = Payment.query.filter_by(merchant_trade_no=merchant_trade_no).first_or_404()
    changed = False

    # If ReturnURL recorded success but user was not upgraded, upgrade now.

    if order.rtn_code == 1 and order.trade_status != "PAID":
        order.mark_paid()
        order.trade_status = "PAID"
        changed = True

    if order.rtn_code == 1 and order.user_id:
        user = User.query.get(order.user_id)
        if user:
            # Only extend if user is not already covered past this payment's paid_at
            paid_at = getattr(order, "paid_at", None) or datetime.now(timezone.utc)
            if (not user.is_subscribed) or (user.subscription_expires_at or datetime.min.replace(tzinfo=timezone.utc)) < paid_at:
                user.activate_from_plan_code(order.plan_code)
                db.session.add(user)
                changed = True

    if changed:
        order.verified = True
        db.session.add(order)
        db.session.commit()

    return jsonify(ok=True, status=order.trade_status, verified=order.verified)

@payments_bp.route("/order_result", methods=["GET", "POST"])
def order_result():
    """
    This is the ECPay OrderResultURL endpoint.
    After a successful (or failed) payment, ECPay redirects the customer here.

    URL example:
        https://ytt.showholdings.com/ecpay/order_result?MerchantTradeNo=YTTxxxxxx

    We:
      - Read the MerchantTradeNo from GET parameters
      - Load the Payment record
      - Decide success/failure
      - Render payment_result.html
    """
    merchant_trade_no = request.values.get("MerchantTradeNo")

    if not merchant_trade_no:
        # No trade number → cannot show order result
        return render_template(
            "payment_result.html",
            success=False,
            message="缺少訂單編號（MerchantTradeNo）。",
            order=None,
        )

    payment = Payment.query.filter_by(merchant_trade_no=merchant_trade_no).first()

    if not payment:
        # Unknown order
        return render_template(
            "payment_result.html",
            success=False,
            message=f"查無此訂單：{merchant_trade_no}",
            order=None,
        )

    # ---- Determine payment success ----
    # The canonical indicator is either:
    #   - payment.trade_status == "PAID"
    #   - OR ECPAY ReturnURL delivered RtnCode == 1
    success = payment.is_success()

    message = None
    if success:
        message = "付款成功，您的訂閱應已啟用。" 
    else:
        # ECPay sometimes delays callback; user might refresh later
        message = payment.rtn_msg or "付款狀態尚未確認。可能需要等待金流回傳。"

    return render_template(
        "payment_result.html",
        success=success,
        message=message,
        order=payment,
    )
