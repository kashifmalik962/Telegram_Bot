from pydantic import BaseModel
from typing import Optional

# Pydantic Model for Subscription Data
class UserSubscription(BaseModel):
    telegram_id: Optional[int] = None
    duration_days: Optional[int] = None  # Dynamic duration in days


# Define input model for validation
class UserCheckRequest(BaseModel):
    user_id: int


class SubscribeRequest(BaseModel):
    phone: str
    duration_days: int

class PhoneCheckRequest(BaseModel):
    phone: str