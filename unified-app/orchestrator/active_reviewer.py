"""
Active Reviewer - Coaches the executor instead of just judging.

The reviewer provides actionable feedback to help the executor complete objectives.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class ReviewStatus(Enum):
    """Review status options."""
    SUCCESS = "success"  # Objective fully complete
    CONTINUE = "continue"  # Partial progress, needs more work
    PIVOT = "pivot"  # Stuck, needs different approach
    FAILED = "failed"  # Exhausted all options


@dataclass
class ReviewResult:
    """Result of reviewing executor progress."""
    status: ReviewStatus
    assessment: str
    missing: List[str]
    next_steps: List[str]
    hints: List[str]
    alternative_strategies: List[str]
    confidence: float


class ActiveReviewer:
    """
    Active reviewer that coaches the executor.
    
    Instead of just marking tasks as failed, provides specific guidance
    on what's missing and how to complete the objective.
    """
    
    def __init__(self, llm_provider):
        self.llm = llm_provider
        self.logger = logging.getLogger(__name__)
    
    async def review_progress(
        self,
        objective: str,
        completed_tasks: List[Dict],
        world_state: Dict,
        attempt: int,
        max_attempts: int = 5
    ) -> ReviewResult:
        """
        Review executor progress and provide actionable feedback.
        
        Args:
            objective: The original objective to complete
            completed_tasks: List of tasks completed so far
            world_state: Current state of the world
            attempt: Current attempt number (0-indexed)
            max_attempts: Maximum attempts allowed
        
        Returns:
            ReviewResult with status and guidance
        """
        self.logger.info(f"[ActiveReviewer] Reviewing progress (attempt {attempt + 1}/{max_attempts})")
        
        prompt = self._build_review_prompt(
            objective, completed_tasks, world_state, attempt, max_attempts
        )
        
        try:
            response = await self.llm.generate(
                prompt=prompt + "\n\nRespond in JSON format with: status, assessment, missing, next_steps, hints, alternative_strategies, confidence"
            )
            
            import json
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                else:
                    raise
            
            return self._parse_review(parsed)
        
        except Exception as e:
            self.logger.error(f"[ActiveReviewer] Review failed: {e}")
            return ReviewResult(
                status=ReviewStatus.CONTINUE,
                assessment="Unable to assess progress",
                missing=["Unknown"],
                next_steps=["Continue with current approach"],
                hints=[],
                alternative_strategies=[],
                confidence=0.5
            )
    
    def _build_review_prompt(
        self,
        objective: str,
        completed_tasks: List[Dict],
        world_state: Dict,
        attempt: int,
        max_attempts: int
    ) -> str:
        """Build the review prompt for the LLM."""
        
        tasks_summary = self._format_tasks(completed_tasks)
        state_summary = self._format_world_state(world_state)
        
        return f"""You are a helpful coach reviewing an AI agent's progress on a task.

ORIGINAL OBJECTIVE:
{objective}

COMPLETED TASKS ({len(completed_tasks)} total):
{tasks_summary}

CURRENT STATE:
{state_summary}

ATTEMPT: {attempt + 1}/{max_attempts}

Your job is to:
1. Assess if the objective is FULLY complete (all parts of the original request)
2. If not complete, identify EXACTLY what's missing
3. Provide SPECIFIC, actionable next steps (not vague suggestions)
4. Give helpful hints to overcome obstacles
5. Suggest alternative approaches if the agent is stuck

Guidelines:
- Be encouraging but honest
- Focus on what's MISSING, not what's done
- Provide concrete actions, not abstract advice
- If stuck on technical issues (selectors, etc), suggest workarounds
- Only mark as "failed" if truly impossible after {max_attempts} attempts

Respond with your assessment and guidance."""
        
        return prompt
    
    def _format_tasks(self, tasks: List[Dict]) -> str:
        """Format completed tasks for review."""
        if not tasks:
            return "No tasks completed yet"
        
        lines = []
        for i, task in enumerate(tasks, 1):
            status = task.get("status", "unknown")
            desc = task.get("description", "Unknown task")
            result = task.get("result", "")
            
            status_emoji = "✅" if status == "success" else "❌"
            lines.append(f"{i}. {status_emoji} {desc}")
            if result:
                lines.append(f"   Result: {result[:100]}...")
        
        return "\n".join(lines)
    
    def _format_world_state(self, world_state: Dict) -> str:
        """Format world state for review."""
        if not world_state:
            return "No state information available"
        
        lines = []
        for key, value in world_state.items():
            if value:
                lines.append(f"- {key}: {value}")
        
        return "\n".join(lines) if lines else "No relevant state"
    
    def _parse_review(self, response: Dict) -> ReviewResult:
        """Parse LLM response into ReviewResult."""
        
        status_str = response.get("status", "continue")
        status = ReviewStatus(status_str)
        
        return ReviewResult(
            status=status,
            assessment=response.get("assessment", ""),
            missing=response.get("missing", []),
            next_steps=response.get("next_steps", []),
            hints=response.get("hints", []),
            alternative_strategies=response.get("alternative_strategies", []),
            confidence=response.get("confidence", 0.5)
        )
    
    def format_feedback_for_executor(self, review: ReviewResult) -> str:
        """Format review feedback for injection into executor context."""
        
        lines = [
            "=== REVIEWER FEEDBACK ===",
            f"Status: {review.status.value.upper()}",
            f"Assessment: {review.assessment}",
        ]
        
        if review.missing:
            lines.append("\nWhat's Missing:")
            for item in review.missing:
                lines.append(f"  ❌ {item}")
        
        if review.next_steps:
            lines.append("\nNext Steps:")
            for i, step in enumerate(review.next_steps, 1):
                lines.append(f"  {i}. {step}")
        
        if review.hints:
            lines.append("\nHints:")
            for hint in review.hints:
                lines.append(f"  💡 {hint}")
        
        if review.alternative_strategies:
            lines.append("\nAlternative Approaches:")
            for strategy in review.alternative_strategies:
                lines.append(f"  🔄 {strategy}")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
