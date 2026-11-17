"""Request/response models. JSON uses camelCase; Python uses snake_case."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- auth ----------

class LoginRequest(CamelModel):
    username: str = Field(min_length=1, max_length=64, examples=["s1001"])
    password: str = Field(min_length=1, max_length=128, examples=["Pass1001!"])


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Lifetime in seconds")
    role: str
    student_no: str | None


class MeResponse(CamelModel):
    user_id: int
    username: str
    role: str
    student_no: str | None
