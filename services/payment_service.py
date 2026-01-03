# ================================================================
# services/payment_service.py — Stripe Checkout (Production Safe)
# ================================================================
import stripe
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from core.config import settings  # ✅ Use centralized configuration

router = APIRouter(prefix="/payments", tags=["Payments"])

# ------------------------
# STRIPE CONFIG
# ------------------------
stripe.api_key = settings.STRIPE_SECRET_KEY


@router.post("/create-checkout-session")
async def create_checkout_session(data: dict):
    """
    Create a Stripe Checkout Session for a subscription.
    """
    price_id = data.get("price_id")
    if not price_id:
        raise HTTPException(status_code=400, detail="Price ID is required")

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1
            }],
            mode="subscription",
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
        )

        return JSONResponse(
            content={
                "checkout_url": checkout_session.url,
                "session_id": checkout_session.id,
                "environment": settings.ENVIRONMENT,
            },
            status_code=200
        )

    except stripe.error.InvalidRequestError as e:
        raise HTTPException(status_code=400, detail=f"Invalid price ID: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
