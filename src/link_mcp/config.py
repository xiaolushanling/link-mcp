"""进程级配置；凭证不进入工具参数、日志或文档快照。"""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_base_url: str = "https://demo.linkl.com.cn/api"
    token: SecretStr = SecretStr("")
    customer_key: SecretStr = SecretStr("")
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)
    services: tuple[str, ...] = ()
    read_only: bool = False
    max_response_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_response_characters: int = Field(default=25000, ge=2000, le=1000000)

    @field_validator("api_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError("LINK_API_BASE_URL 应为不含凭证、查询串或片段的 HTTP(S) 网关地址")
        # Trigger port validation here, before constructing an upstream request.
        _ = parts.port
        return value

    @field_validator("token", "customer_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if any(character in value.get_secret_value() for character in "\r\n\x00"):
            raise ValueError("凭证不得包含换行或空字符")
        return value

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        names = {
            "api_base_url": "LINK_API_BASE_URL",
            "token": "LINK_TOKEN",
            "customer_key": "LINK_CUSTOMER_KEY",
            "timeout_seconds": "LINK_TIMEOUT_SECONDS",
            "read_only": "LINK_READ_ONLY",
            "max_response_bytes": "LINK_MAX_RESPONSE_BYTES",
            "max_response_characters": "LINK_MAX_RESPONSE_CHARACTERS",
        }
        values = {field: env[name] for field, name in names.items() if name in env}
        values["services"] = tuple(
            dict.fromkeys(
                item.strip() for item in env.get("LINK_SERVICES", "").split(",") if item.strip()
            )
        )
        return cls.model_validate(values)
