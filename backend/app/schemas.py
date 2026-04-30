import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ALLOWED_API_KEY_SCOPES = frozenset({"jobs:read", "jobs:write"})
DEFAULT_API_KEY_SCOPES = ["jobs:read", "jobs:write"]


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


class APIKeyCreateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: DEFAULT_API_KEY_SCOPES.copy())
    expires_at: datetime | None = Field(default=None, alias="expiresAt")

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("API key name cannot be blank")
        return name

    @field_validator("scopes")
    @classmethod
    def scopes_must_be_allowed(cls, value: list[str]) -> list[str]:
        deduplicated = list(dict.fromkeys(value))
        if not deduplicated:
            raise ValueError("At least one scope is required")
        invalid_scopes = sorted(set(deduplicated) - ALLOWED_API_KEY_SCOPES)
        if invalid_scopes:
            raise ValueError(f"Unsupported API key scopes: {', '.join(invalid_scopes)}")
        return deduplicated

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_in_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expiresAt must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("expiresAt must be in the future")
        return value


class APIKeyResponse(CamelModel):
    api_key_id: uuid.UUID = Field(alias="apiKeyId")
    name: str
    key_prefix: str = Field(alias="keyPrefix")
    scopes: list[str]
    is_active: bool = Field(alias="isActive")
    expires_at: datetime | None = Field(alias="expiresAt")
    last_used_at: datetime | None = Field(alias="lastUsedAt")
    created_at: datetime = Field(alias="createdAt")
    revoked_at: datetime | None = Field(alias="revokedAt")


class APIKeyCreateResponse(APIKeyResponse):
    api_key: str = Field(alias="apiKey")
