"""Objective planning and validation for Trinity Core."""

from __future__ import annotations

import json
import re
from typing import Any

from .llm.llm_provider import LLMProvider
from .models import ObjectivePlan, SubObjective
from .strategy_registry import StrategyRegistry

_SERVER_DOMAIN: dict[str, str] = {
    "browser_mcp": "web",
    "puppeteer_mcp": "web",
    "cli_mcp": "cli",
    "desktop_mcp": "desktop",
}

_DOMAIN_SERVER: dict[str, str] = {
    "web": "browser_mcp",
    "browser": "browser_mcp",
    "cli": "cli_mcp",
    "desktop": "desktop_mcp",
}

_WEB_HINTS = (
    "browser", "web", "url", "http", "https", "site", "page", "github",
    "python.org", "docs.", "localhost", "dashboard", "navigate", "search",
    "look up", "extract",
)
_DESKTOP_HINTS = (
    "desktop", "notepad", "window", "calculator", "application", "app",
    "launch", "open notepad", "save", "type",
)
_CLI_HINTS = (
    "cli", "terminal", "command", "powershell", "shell", "file", "folder",
    "directory", "log", "logs", "run ", "write", "create", "count",
    "tasklist", "curl", "wmic", "systeminfo", "dir ", "python --version",
)


class ObjectivePlanner:
    """Create and validate sub-objectives for finishing a task."""

    def __init__(
        self,
        *,
        strategy_registry: StrategyRegistry,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.strategy_registry = strategy_registry
        self.llm_provider = llm_provider

    async def plan(self, task: Any, *, validation_errors: list[str] | None = None) -> ObjectivePlan:
        """Build an objective plan.

        The LLM is allowed to draft the plan, but deterministic routing and
        validation normalize the result before execution. If the LLM returns
        non-JSON, tool calls, or an invalid shape, the approved sub-objectives
        become the source of truth.
        """
        if not self._needs_llm_plan(task):
            normalized = self._normalize_plan(task, self._fallback_plan(task))
            errors = self.validate(normalized)
            if errors:
                raise ValueError("; ".join(errors))
            return normalized
        llm_plan = await self._try_llm_plan(task, validation_errors=validation_errors or [])
        if llm_plan is None:
            llm_plan = self._fallback_plan(task)
        normalized = self._normalize_plan(task, llm_plan)
        errors = self.validate(normalized)
        if errors:
            raise ValueError("; ".join(errors))
        return normalized

    def _needs_llm_plan(self, task: Any) -> bool:
        domain = str(getattr(task, "domain", "") or "").lower()
        sub_objectives = list(getattr(task, "sub_objectives", []) or [])
        if domain in {"mixed", "cross"}:
            return True
        return len(sub_objectives) > 1

    def validate(self, plan: ObjectivePlan) -> list[str]:
        errors: list[str] = []
        known_servers = {s.strategy_id: s.domain for s in self.strategy_registry.list()}
        for sub in plan.sub_objectives:
            if not sub.objective.strip():
                errors.append(f"{sub.sub_objective_id}: missing objective")
            if not sub.postconditions:
                errors.append(f"{sub.sub_objective_id}: missing postconditions")
            if sub.target_server not in known_servers:
                errors.append(f"{sub.sub_objective_id}: unknown target_server {sub.target_server!r}")
                continue
            expected_domain = known_servers[sub.target_server]
            if expected_domain != sub.domain:
                errors.append(
                    f"{sub.sub_objective_id}: target_server {sub.target_server!r} "
                    f"has domain {expected_domain!r}, not {sub.domain!r}"
                )
        return errors

    async def _try_llm_plan(
        self,
        task: Any,
        *,
        validation_errors: list[str],
    ) -> ObjectivePlan | None:
        if self.llm_provider is None:
            return None
        servers = [
            {
                "strategy_id": s.strategy_id,
                "domain": s.domain,
                "description": s.description,
                "tools": s.metadata.get("live_tools", []),
                "constraints": s.metadata.get("constraints", []),
            }
            for s in self.strategy_registry.list()
        ]
        prompt = (
            "Create an objective plan as strict JSON. The software owns finishing "
            "the objective by any valid route. Split mixed work into domain-scoped "
            "sub-objectives. Return only JSON with keys: objective_id, objective, "
            "strategy, sub_objectives. Each sub-objective must include "
            "sub_objective_id, objective, domain, target_server, preconditions, "
            "postconditions, timeout, depends_on.\n\n"
            f"Objective id: {task.task_id}\n"
            f"Objective: {task.description}\n"
            f"Approved sub-objectives: {json.dumps(task.sub_objectives)}\n"
            f"Available servers: {json.dumps(servers)}\n"
            f"Validation errors to fix: {json.dumps(validation_errors)}"
        )
        try:
            response = await self.llm_provider.call(
                messages=[{"role": "user", "content": prompt}],
                tools={},
            )
        except Exception:
            return None
        if response.tool_calls or not response.text:
            return None
        raw = _extract_json(response.text)
        if raw is None:
            return None
        try:
            return ObjectivePlan.model_validate(raw)
        except Exception:
            return None

    def _fallback_plan(self, task: Any) -> ObjectivePlan:
        items = list(task.sub_objectives or []) or [task.description]
        sub_objectives: list[SubObjective] = []
        for index, objective in enumerate(items, start=1):
            domain, target_server = self._route_objective(
                str(objective),
                task_domain=task.domain,
                target_server=getattr(task, "target_server", None),
            )
            sub_objectives.append(
                SubObjective(
                    sub_objective_id=f"sub-{index}",
                    objective=str(objective),
                    domain=domain,
                    target_server=target_server,
                    preconditions=[],
                    postconditions=[str(objective)],
                    timeout=task.timeout,
                    depends_on=[],
                )
            )
        return ObjectivePlan(
            objective_id=task.task_id,
            objective=task.description,
            sub_objectives=sub_objectives,
        )

    def _normalize_plan(self, task: Any, plan: ObjectivePlan) -> ObjectivePlan:
        normalized: list[SubObjective] = []
        source_steps = plan.sub_objectives or self._fallback_plan(task).sub_objectives
        for index, sub in enumerate(source_steps, start=1):
            objective = sub.objective or task.description
            domain, target_server = self._route_objective(
                objective,
                task_domain=sub.domain or task.domain,
                target_server=sub.target_server or getattr(task, "target_server", None),
            )
            normalized.append(
                sub.model_copy(
                    update={
                        "sub_objective_id": sub.sub_objective_id or f"sub-{index}",
                        "objective": objective,
                        "domain": domain,
                        "target_server": target_server,
                        "postconditions": list(sub.postconditions or [objective]),
                        "preconditions": list(sub.preconditions or []),
                        "depends_on": list(sub.depends_on or []),
                        "timeout": sub.timeout if sub.timeout is not None else task.timeout,
                    }
                )
            )
        return ObjectivePlan(
            objective_id=plan.objective_id or task.task_id,
            objective=plan.objective or task.description,
            strategy=plan.strategy or "finish_objective",
            sub_objectives=normalized,
        )

    def _route_objective(
        self,
        objective: str,
        *,
        task_domain: str,
        target_server: str | None = None,
    ) -> tuple[str, str]:
        text = objective.lower()
        domain_hint = (task_domain or "").lower()
        target_hint = (target_server or "").strip()
        if target_hint:
            try:
                strategy = self.strategy_registry.get(target_hint)
                return strategy.domain, strategy.strategy_id
            except KeyError:
                pass
        if domain_hint and domain_hint not in {"mixed", "cross", "browser"}:
            server = self._server_for_domain(domain_hint)
            if server:
                return domain_hint, server
        if domain_hint in {"web", "browser"} and not _contains_any(text, _CLI_HINTS + _DESKTOP_HINTS):
            return "web", self._server_for_domain("web")
        if domain_hint == "desktop" and not _contains_any(text, _CLI_HINTS + _WEB_HINTS):
            return "desktop", self._server_for_domain("desktop")
        if domain_hint == "cli" and not _contains_any(text, _WEB_HINTS + _DESKTOP_HINTS):
            return "cli", self._server_for_domain("cli")
        if _contains_any(text, _DESKTOP_HINTS):
            return "desktop", self._server_for_domain("desktop")
        if _contains_any(text, _WEB_HINTS):
            return "web", self._server_for_domain("web")
        if _contains_any(text, _CLI_HINTS):
            return "cli", self._server_for_domain("cli")
        try:
            server = self.strategy_registry.suggest_strategy_for_objective(objective)
            domain = _SERVER_DOMAIN.get(server, self.strategy_registry.get(server).domain)
            return domain, server
        except Exception:
            server = self._server_for_domain("cli") or next(
                (strategy.strategy_id for strategy in self.strategy_registry.list()),
                "cli_mcp",
            )
            try:
                return self.strategy_registry.get(server).domain, server
            except Exception:
                return "cli", server

    def _server_for_domain(self, domain: str) -> str:
        for strategy in self.strategy_registry.list():
            if strategy.domain == domain:
                return strategy.strategy_id
        return _DOMAIN_SERVER.get(domain, "")


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _extract_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None
