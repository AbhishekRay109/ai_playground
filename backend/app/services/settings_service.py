"""Runtime settings that users change from the Settings panel (persisted in SQLite)."""

from __future__ import annotations

from app.core.config import Settings
from app.models.db import Database
from app.models.entities import AppSetting
from app.schemas.common import RuntimeConfig, RuntimeConfigUpdate

_KEY = "runtime_config"


class SettingsService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self._current = self._load()

    def _defaults(self) -> RuntimeConfig:
        s = self.settings
        return RuntimeConfig(
            chat_model=s.ollama_model,
            temperature=s.llm_temperature,
            max_tokens=s.llm_max_tokens,
            llm_timeout_s=s.llm_timeout_s,
            embedding_model=s.embedding_model,
            rag_top_k=s.rag_top_k,
            rag_score_threshold=s.rag_score_threshold,
        )

    def _load(self) -> RuntimeConfig:
        defaults = self._defaults()
        with self.db.session() as session:
            row = session.get(AppSetting, _KEY)
            if row and isinstance(row.value, dict):
                try:
                    return RuntimeConfig(**{**defaults.model_dump(), **row.value})
                except ValueError:
                    return defaults
        return defaults

    @property
    def current(self) -> RuntimeConfig:
        return self._current

    def update(self, update: RuntimeConfigUpdate) -> RuntimeConfig:
        merged = RuntimeConfig(**{**self._current.model_dump(), **update.model_dump(exclude_none=True)})
        with self.db.session() as session:
            row = session.get(AppSetting, _KEY)
            if row is None:
                session.add(AppSetting(key=_KEY, value=merged.model_dump()))
            else:
                row.value = merged.model_dump()
        self._current = merged
        return merged

    def reset(self) -> RuntimeConfig:
        with self.db.session() as session:
            row = session.get(AppSetting, _KEY)
            if row:
                session.delete(row)
        self._current = self._defaults()
        return self._current
