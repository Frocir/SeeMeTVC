from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: str
    balance: float
    is_active: bool

    model_config = {"from_attributes": True}


class MeOut(UserOut):
    balance_unit: str


class ChannelCreate(BaseModel):
    name: str
    provider: str = "fal"
    base_url: str = ""
    api_key: str
    model_id: str
    upstream_model: str
    cost_per_second: float = 1.0
    priority: int = 0
    enabled: bool = True
    remark: str = ""


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    upstream_model: str | None = None
    cost_per_second: float | None = None
    priority: int | None = None
    enabled: bool | None = None
    remark: str | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    model_id: str
    upstream_model: str
    cost_per_second: float
    priority: int
    enabled: bool
    remark: str
    # Masked for admin list safety
    api_key_masked: str

    model_config = {"from_attributes": True}


class ModelOptionOut(BaseModel):
    model_id: str
    cost_per_second: float
    provider: str


class GenerateIn(BaseModel):
    model_id: str
    prompt: str = Field(min_length=1, max_length=4000)
    image_url: str | None = None
    duration_seconds: int = Field(default=5, ge=2, le=30)


class JobOut(BaseModel):
    id: int
    model_id: str
    prompt: str
    image_url: str | None
    duration_seconds: int
    status: str
    cost: float
    balance_after: float | None
    result_url: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminSetBalanceIn(BaseModel):
    balance: float = Field(ge=0)


class AdminUserOut(UserOut):
    pass
