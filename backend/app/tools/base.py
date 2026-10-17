"""Tool interface shared by manual modes and the agent.

Every tool declares a Pydantic argument model (its schema), a description, and returns a
:class:`ToolOutput`: a short summary for the trace, bounded text for the model to observe,
citable evidence, and structured details for the execution panel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from app.schemas.chat import Source, ToolName
from app.services.execution import EffectiveOptions

if TYPE_CHECKING:
    from app.core.container import Container
    from app.services.llm_service import LLMResult


@dataclass
class Evidence:
    """Citable evidence: the source shown to the user plus the full text given to the model."""

    source: Source
    text: str


@dataclass
class ToolOutput:
    summary: str
    observation: str  # bounded text the agent planner sees
    evidence: list[Evidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    llm_results: list[LLMResult] = field(default_factory=list)
    embedding_model: str | None = None
    status: str = "success"  # success | error  (error = tool ran but could not produce a result)
    error: str | None = None


@dataclass
class ToolContext:
    container: Container
    options: EffectiveOptions
    question: str


class Tool(ABC):
    name: ClassVar[ToolName]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutput: ...

    def input_summary(self, args: BaseModel) -> str:
        data = args.model_dump(exclude_none=True)
        text = ", ".join(f"{k}={v!r}" for k, v in data.items())
        return text[:200]

    def schema_for_prompt(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        return {
            "name": self.name.value,
            "description": self.description,
            "arguments": {k: v for k, v in schema.items() if k in ("properties", "required")},
        }


def bound(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…[truncated {len(text) - limit} chars]"
