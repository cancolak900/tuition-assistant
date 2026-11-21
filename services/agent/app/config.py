"""Agent settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The agent reaches the Tuition API only through the gateway, with the user's own token.
    gateway_url: str = Field("http://kong:8000", description="Kong proxy base URL (no trailing /api/v1)")
    mcp_url: str = Field("http://mcp-server:8100/mcp", description="MCP server streamable HTTP endpoint")

    # Same secret and issuer as the Tuition API, so the agent can verify the caller itself.
    jwt_secret: str = Field(..., min_length=32)
    jwt_issuer: str = "tuition-auth"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_fallback_model: str = Field("gemini-flash-lite-latest,gemini-3.5-flash-lite", description="Comma-separated models tried in order when the main one is overloaded or out of quota; empty = none")
    llm_timeout_seconds: float = Field(25, gt=0, description="Per LLM call")
    turn_timeout_seconds: float = Field(80, gt=0, description="Whole chat turn; below Kong's 90 s read timeout")
    llm_temperature: float = Field(0.2, ge=0, le=1)
    max_tool_rounds: int = Field(5, ge=1, le=10)
    max_history_messages: int = Field(20, ge=2, le=100)

    session_ttl_minutes: int = Field(30, ge=1)
    pending_action_ttl_minutes: int = Field(5, ge=1)
    max_message_chars: int = Field(2000, ge=10)

    api_prefix: str = "/api/v1/agent"
    app_name: str = "Tuition Assistant Agent"
    app_version: str = "1.0.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
