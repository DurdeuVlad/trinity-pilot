"""
Integration layer for Active Reviewer in execution flow.

This shows how to integrate the active reviewer into the existing
execution_runner.py without breaking current functionality.
"""
from typing import Optional
from .active_reviewer import ActiveReviewer, ReviewStatus
from .execution_context import ExecutionContext


class ActiveReviewIntegration:
    """
    Wrapper to integrate active reviewer into execution flow.
    
    Usage in execution_runner.py:
    
        self.active_review = ActiveReviewIntegration(
            reviewer=ActiveReviewer(llm_provider),
            max_review_attempts=5
        )
        
        # In _attempt_objective:
        result = await self.active_review.execute_with_review(
            ctx=ctx,
            obj_index=obj_index,
            executor_func=self._execute_single_attempt
        )
    """
    
    def __init__(self, reviewer: ActiveReviewer, max_review_attempts: int = 5):
        self.reviewer = reviewer
        self.max_attempts = max_review_attempts
    
    async def execute_with_review(
        self,
        ctx: ExecutionContext,
        obj_index: int,
        executor_func
    ):
        """
        Execute objective with active reviewer feedback loop.
        
        Args:
            ctx: Execution context
            obj_index: Current objective index
            executor_func: Function to execute one attempt (async)
        
        Returns:
            Final execution result
        """
        objective = ctx.objectives[obj_index]
        
        for attempt in range(self.max_attempts):
            # Execute one attempt
            result = await executor_func(ctx, obj_index, attempt)
            
            # Collect completed tasks for this objective
            completed_tasks = self._get_completed_tasks(ctx, obj_index)
            
            # Review progress
            review = await self.reviewer.review_progress(
                objective=objective,
                completed_tasks=completed_tasks,
                world_state=ctx.world_state.__dict__,
                attempt=attempt,
                max_attempts=self.max_attempts
            )
            
            # Log feedback
            feedback = self.reviewer.format_feedback_for_executor(review)
            print(feedback)  # Or use proper logging
            
            # Handle review status
            if review.status == ReviewStatus.SUCCESS:
                # Objective complete!
                return result
            
            elif review.status == ReviewStatus.CONTINUE:
                # Inject feedback into context for next attempt
                self._inject_feedback(ctx, review)
                continue
            
            elif review.status == ReviewStatus.PIVOT:
                # Suggest alternative approach
                self._inject_pivot_strategy(ctx, review)
                continue
            
            else:  # FAILED
                # Only fail after exhausting attempts
                if attempt >= self.max_attempts - 1:
                    return result
                continue
        
        # Exhausted all attempts
        return result
    
    def _get_completed_tasks(self, ctx: ExecutionContext, obj_index: int):
        """Extract completed tasks for current objective."""
        # This depends on how tasks are tracked in your context
        # Adjust based on actual ExecutionContext structure
        
        completed = []
        
        # Example: if you track module results
        if hasattr(ctx, 'module_results'):
            for module, result in ctx.module_results.items():
                completed.append({
                    "description": f"{module} task",
                    "status": result.get("status", "unknown"),
                    "result": result.get("output", "")
                })
        
        # Example: if you track accumulated state
        if hasattr(ctx, 'accumulated_state'):
            for key, value in ctx.accumulated_state.items():
                if key.startswith(f"objective_{obj_index + 1}_"):
                    completed.append({
                        "description": key,
                        "status": "success" if value else "unknown",
                        "result": str(value)
                    })
        
        return completed
    
    def _inject_feedback(self, ctx: ExecutionContext, review):
        """Inject reviewer feedback into context for next attempt."""
        
        # Add feedback to context so planner can see it
        if not hasattr(ctx, 'reviewer_feedback'):
            ctx.reviewer_feedback = []
        
        ctx.reviewer_feedback.append({
            "missing": review.missing,
            "next_steps": review.next_steps,
            "hints": review.hints
        })
        
        # Update world state with guidance
        if hasattr(ctx, 'world_state'):
            ctx.world_state.reviewer_guidance = "\n".join(review.next_steps)
    
    def _inject_pivot_strategy(self, ctx: ExecutionContext, review):
        """Inject alternative strategy suggestion."""
        
        if not hasattr(ctx, 'alternative_strategies'):
            ctx.alternative_strategies = []
        
        ctx.alternative_strategies.extend(review.alternative_strategies)
        
        # Flag that we should try a different approach
        if hasattr(ctx, 'world_state'):
            ctx.world_state.should_pivot = True
            ctx.world_state.pivot_reason = review.assessment


# Example integration in execution_runner.py:
"""
class TaskExecutionRunner:
    def __init__(self, ...):
        # ... existing init ...
        
        # Add active reviewer
        self.active_review = ActiveReviewIntegration(
            reviewer=ActiveReviewer(self.llm_provider),
            max_review_attempts=5
        )
    
    async def _attempt_objective(self, ctx, obj_index):
        '''Execute objective with active review.'''
        
        # Use active review wrapper
        return await self.active_review.execute_with_review(
            ctx=ctx,
            obj_index=obj_index,
            executor_func=self._execute_single_attempt
        )
    
    async def _execute_single_attempt(self, ctx, obj_index, attempt):
        '''Execute one attempt of the objective.'''
        
        # Check for reviewer feedback
        if hasattr(ctx, 'reviewer_feedback') and ctx.reviewer_feedback:
            latest_feedback = ctx.reviewer_feedback[-1]
            # Inject into planner prompt
            self.logger.info(f"Reviewer says: {latest_feedback['next_steps']}")
        
        # ... existing execution logic ...
        
        return result
"""
