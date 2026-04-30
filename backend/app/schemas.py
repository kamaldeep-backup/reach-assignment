import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RegisterRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    tenant_name: str = Field(alias="tenantName", min_length=1, max_length=200)

    @field_validator("tenant_name")
    @classmethod
    def tenant_name_must_not_be_blank(cls, value: str) -> str:
        tenant_name = value.strip()
        if not tenant_name:
            raise ValueError("Tenant name cannot be blank")
        return tenant_name


class RegisterResponse(CamelModel):
    user_id: uuid.UUID = Field(alias="userId")
    tenant_id: uuid.UUID = Field(alias="tenantId")
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TenantSummary(CamelModel):
    id: uuid.UUID
    name: str
    role: str


class CurrentUserResponse(CamelModel):
    user_id: uuid.UUID = Field(alias="userId")
    tenant_id: uuid.UUID = Field(alias="tenantId")
    email: EmailStr
    tenant: TenantSummary
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
