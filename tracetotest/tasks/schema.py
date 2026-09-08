"""Declarative task definitions used by runners and deterministic verifiers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentSpec(TaskModel):
    fixture_id: str
    fixture_version: str
    fixture_path: str
    start_path: str = "/"
    faults: list[str] = Field(default_factory=list)

    @field_validator("fixture_path")
    @classmethod
    def fixture_path_must_be_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("fixture_path must be a repository-relative path without '..'")
        return path.as_posix()

    @field_validator("start_path")
    @classmethod
    def start_path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("start_path must be an absolute URL path")
        return value


class LimitsSpec(TaskModel):
    max_steps: int = Field(default=25, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    max_model_calls: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0)


class VerifierSpec(TaskModel):
    verifier_id: str
    verifier_version: str
    config: dict[str, Any] = Field(default_factory=dict)


class SafetySpec(TaskModel):
    allow_download: bool = False
    allow_database_mutation: bool = False
    allow_external_upload: bool = False
    prohibited_actions: list[str] = Field(default_factory=list)


class TaskSpec(TaskModel):
    task_id: str
    version: str
    suite_id: str
    instruction: str = Field(min_length=1)
    environment: EnvironmentSpec
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    verifier: VerifierSpec
    safety: SafetySpec = Field(default_factory=SafetySpec)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "TaskSpec":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix.casefold() == ".json" else yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"Task file must contain an object: {path}")
        return cls.model_validate(data)

    @staticmethod
    def content_sha256(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
