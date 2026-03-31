"""Checkpoint management for progress preservation and recovery."""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

try:
    from .execution_context import ExecutionContext
except ImportError:
    from execution_context import ExecutionContext

logger = logging.getLogger(__name__)


_DEFAULT_CHECKPOINT_DIR = (
    Path(__file__).resolve().parent.parent / "_runtime" / "checkpoints"
)


class CheckpointManager:
    """Manages checkpoint persistence and recovery for orchestrator execution.

    Checkpoints enable progress preservation and resume from failure by saving
    ExecutionContext state after each successful objective.
    """

    def __init__(
        self,
        checkpoint_dir: Optional[Path] = None,
        max_checkpoints: int = 10,
        retention_days: int = 7
    ) -> None:
        """Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory for checkpoint storage (default: _runtime/checkpoints)
            max_checkpoints: Maximum checkpoints to keep per task
            retention_days: Days to retain checkpoints before cleanup
        """
        self.checkpoint_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
        self.max_checkpoints = max_checkpoints
        self.retention_days = retention_days
        self._ensure_checkpoint_dir()
    
    def _ensure_checkpoint_dir(self) -> None:
        """Ensure checkpoint directory exists."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save_checkpoint(
        self,
        task_id: str,
        context: ExecutionContext,
        objective_index: int
    ) -> str:
        """Save checkpoint for current execution state.
        
        Args:
            task_id: Unique task identifier
            context: Current execution context
            objective_index: Index of completed objective
            
        Returns:
            Checkpoint ID
        """
        checkpoint_id = f"{task_id}_obj{objective_index}_{int(time.time())}"
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        
        try:
            # Serialize context
            checkpoint_data = {
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "objective_index": objective_index,
                "timestamp": time.time(),
                "context": self._serialize_context(context)
            }
            
            # Write to file
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)
            
            logger.info(f"[CheckpointManager] Saved checkpoint: {checkpoint_id}")
            
            # Cleanup old checkpoints
            self._cleanup_old_checkpoints(task_id)
            
            return checkpoint_id
            
        except Exception as exc:
            logger.error(f"[CheckpointManager] Failed to save checkpoint: {exc}")
            raise
    
    def load_checkpoint(self, checkpoint_id: str) -> tuple[ExecutionContext, int]:
        """Load checkpoint by ID.
        
        Args:
            checkpoint_id: Checkpoint identifier
            
        Returns:
            Tuple of (ExecutionContext, objective_index)
            
        Raises:
            FileNotFoundError: If checkpoint doesn't exist
            ValueError: If checkpoint is invalid
        """
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")
        
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            context = self._deserialize_context(checkpoint_data["context"])
            objective_index = checkpoint_data["objective_index"]
            
            logger.info(f"[CheckpointManager] Loaded checkpoint: {checkpoint_id}")
            
            return context, objective_index
            
        except Exception as exc:
            logger.error(f"[CheckpointManager] Failed to load checkpoint: {exc}")
            raise ValueError(f"Invalid checkpoint: {exc}") from exc
    
    def get_latest_checkpoint(self, task_id: str) -> Optional[str]:
        """Get the most recent checkpoint for a task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Checkpoint ID or None if no checkpoints exist
        """
        checkpoints = list(self.checkpoint_dir.glob(f"{task_id}_*.json"))
        
        if not checkpoints:
            return None
        
        # Sort by modification time (most recent first)
        checkpoints.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        checkpoint_id = checkpoints[0].stem
        logger.info(f"[CheckpointManager] Latest checkpoint for {task_id}: {checkpoint_id}")
        
        return checkpoint_id
    
    def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Delete a specific checkpoint.
        
        Args:
            checkpoint_id: Checkpoint identifier
        """
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.info(f"[CheckpointManager] Deleted checkpoint: {checkpoint_id}")
    
    def delete_task_checkpoints(self, task_id: str) -> int:
        """Delete all checkpoints for a task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Number of checkpoints deleted
        """
        checkpoints = list(self.checkpoint_dir.glob(f"{task_id}_*.json"))
        count = 0
        
        for checkpoint_path in checkpoints:
            checkpoint_path.unlink()
            count += 1
        
        logger.info(f"[CheckpointManager] Deleted {count} checkpoints for task {task_id}")
        
        return count
    
    def _cleanup_old_checkpoints(self, task_id: str) -> None:
        """Remove old checkpoints exceeding retention limits.
        
        Args:
            task_id: Task identifier
        """
        checkpoints = list(self.checkpoint_dir.glob(f"{task_id}_*.json"))
        
        # Sort by modification time (oldest first)
        checkpoints.sort(key=lambda p: p.stat().st_mtime)
        
        # Remove excess checkpoints
        if len(checkpoints) > self.max_checkpoints:
            excess = checkpoints[:len(checkpoints) - self.max_checkpoints]
            for checkpoint_path in excess:
                try:
                    checkpoint_path.unlink()
                    logger.debug(f"[CheckpointManager] Cleaned up old checkpoint: {checkpoint_path.stem}")
                except FileNotFoundError:
                    pass  # Already deleted
        
        # Remove checkpoints older than retention period
        cutoff_time = time.time() - (self.retention_days * 24 * 60 * 60)
        for checkpoint_path in checkpoints:
            try:
                if checkpoint_path.exists() and checkpoint_path.stat().st_mtime < cutoff_time:
                    checkpoint_path.unlink()
                    logger.debug(f"[CheckpointManager] Cleaned up expired checkpoint: {checkpoint_path.stem}")
            except FileNotFoundError:
                pass  # Already deleted
    
    def _serialize_context(self, context: ExecutionContext) -> dict:
        """Serialize ExecutionContext to JSON-compatible dict.
        
        Args:
            context: Execution context to serialize
            
        Returns:
            JSON-serializable dictionary
        """
        # Convert dataclass to dict
        context_dict = asdict(context)
        
        # Handle any non-serializable types
        # (ExecutionContext uses basic types, so this should work directly)
        
        return context_dict
    
    def _deserialize_context(self, context_dict: dict) -> ExecutionContext:
        """Deserialize ExecutionContext from dict.

        Args:
            context_dict: Dictionary from JSON

        Returns:
            ExecutionContext instance
        """
        # Import here to avoid circular dependency
        try:
            from .execution_context import ErrorRecord, ModuleResult, WorldState
        except ImportError:
            from execution_context import ErrorRecord, ModuleResult, WorldState

        # Reconstruct nested dataclasses
        module_results = {}
        for module, result_dict in context_dict.get("module_results", {}).items():
            module_results[module] = ModuleResult(**result_dict)

        error_history = []
        for error_dict in context_dict.get("error_history", []):
            error_history.append(ErrorRecord(**error_dict))

        # Reconstruct WorldState from serialized dict (added in world-state contract).
        # Old checkpoints that pre-date this field will lack the key; in that case
        # a fresh empty WorldState is used so deserialization never raises.
        world_state = WorldState()
        raw_ws = context_dict.get("world_state")
        if isinstance(raw_ws, dict):
            world_state = WorldState(
                active_app=raw_ws.get("active_app"),
                active_window=raw_ws.get("active_window"),
                active_document=raw_ws.get("active_document"),
                last_text_artifact=raw_ws.get("last_text_artifact"),
                last_opened_url=raw_ws.get("last_opened_url"),
                app_launch_mode=raw_ws.get("app_launch_mode"),
                document_state=raw_ws.get("document_state"),
            )

        # Create ExecutionContext
        context = ExecutionContext(
            objective=context_dict["objective"],
            module_results=module_results,
            learned_constraints=context_dict.get("learned_constraints", []),
            accumulated_state=context_dict.get("accumulated_state", {}),
            error_history=error_history,
            retry_count=context_dict.get("retry_count", 0),
            fallback_level=context_dict.get("fallback_level", 0),
            checkpoint_id=context_dict.get("checkpoint_id"),
            world_state=world_state,
        )

        return context
    
    def get_checkpoint_size(self, checkpoint_id: str) -> int:
        """Get size of checkpoint file in bytes.
        
        Args:
            checkpoint_id: Checkpoint identifier
            
        Returns:
            File size in bytes
        """
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        
        if not checkpoint_path.exists():
            return 0
        
        return checkpoint_path.stat().st_size
    
    def get_total_size(self, task_id: Optional[str] = None) -> int:
        """Get total size of checkpoints.
        
        Args:
            task_id: Optional task ID to filter by
            
        Returns:
            Total size in bytes
        """
        if task_id:
            checkpoints = list(self.checkpoint_dir.glob(f"{task_id}_*.json"))
        else:
            checkpoints = list(self.checkpoint_dir.glob("*.json"))
        
        return sum(p.stat().st_size for p in checkpoints)
