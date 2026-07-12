from pydantic import BaseModel, Field


MIN_STACK_COUNT = 4
MAX_STACK_COUNT = 16
DEFAULT_STACK_COUNT = 4


class DemoStartRequest(BaseModel):
    stack_count: int = Field(
        default=DEFAULT_STACK_COUNT,
        ge=MIN_STACK_COUNT,
        le=MAX_STACK_COUNT,
        description="Number of chips to stack in the vision demo.",
    )
