"""Unit tests for CheckpointManager."""
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

import sys
from pathlib import Path as PathLib

# Add orchestrator to path
sys.path.insert(0, str(PathLib(__file__).parent.parent.parent / "orchestrator"))

from checkpoint_manager import CheckpointManager
from execution_context import ErrorRecord, ExecutionContext, ModuleResult, WorldState


@pytest.fixture
def temp_checkpoint_dir(tmp_path):
    """Create temporary checkpoint directory."""
    return tmp_path / "checkpoints"


@pytest.fixture
def checkpoint_manager(temp_checkpoint_dir):
    """Create CheckpointManager with temp directory."""
    return CheckpointManager(checkpoint_dir=temp_checkpoint_dir, max_checkpoints=5)


@pytest.fixture
def sample_context():
    """Create sample ExecutionContext."""
    context = ExecutionContext(objective="Test objective")
    context.add_result("web", ModuleResult("web", "success", "OK"))
    context.add_error(ErrorRecord("transient", "Timeout", {}))
    context.add_constraint("Use Windows commands")
    context.update_state("file", "/tmp/test.txt")
    return context


class TestCheckpointManagerInit:
    """Test CheckpointManager initialization."""
    
    def test_default_init(self):
        """Test initialization with defaults."""
        manager = CheckpointManager()

        assert manager.checkpoint_dir.name == "checkpoints"
        assert manager.checkpoint_dir.parent.name == "_runtime"
        assert manager.max_checkpoints == 10
        assert manager.retention_days == 7
    
    def test_custom_init(self, temp_checkpoint_dir):
        """Test initialization with custom parameters."""
        manager = CheckpointManager(
            checkpoint_dir=temp_checkpoint_dir,
            max_checkpoints=5,
            retention_days=3
        )
        
        assert manager.checkpoint_dir == temp_checkpoint_dir
        assert manager.max_checkpoints == 5
        assert manager.retention_days == 3
    
    def test_creates_directory(self, temp_checkpoint_dir):
        """Test that checkpoint directory is created."""
        assert not temp_checkpoint_dir.exists()
        
        CheckpointManager(checkpoint_dir=temp_checkpoint_dir)
        
        assert temp_checkpoint_dir.exists()
        assert temp_checkpoint_dir.is_dir()


class TestSaveCheckpoint:
    """Test checkpoint saving."""
    
    def test_save_checkpoint(self, checkpoint_manager, sample_context):
        """Test saving a checkpoint."""
        checkpoint_id = checkpoint_manager.save_checkpoint(
            task_id="task1",
            context=sample_context,
            objective_index=0
        )
        
        assert checkpoint_id.startswith("task1_obj0_")
        
        # Verify file exists
        checkpoint_path = checkpoint_manager.checkpoint_dir / f"{checkpoint_id}.json"
        assert checkpoint_path.exists()
    
    def test_checkpoint_content(self, checkpoint_manager, sample_context):
        """Test checkpoint file content."""
        checkpoint_id = checkpoint_manager.save_checkpoint(
            task_id="task1",
            context=sample_context,
            objective_index=0
        )
        
        checkpoint_path = checkpoint_manager.checkpoint_dir / f"{checkpoint_id}.json"
        with open(checkpoint_path, 'r') as f:
            data = json.load(f)
        
        assert data["checkpoint_id"] == checkpoint_id
        assert data["task_id"] == "task1"
        assert data["objective_index"] == 0
        assert "timestamp" in data
        assert "context" in data
        
        # Verify context data
        context_data = data["context"]
        assert context_data["objective"] == "Test objective"
        assert len(context_data["module_results"]) == 1
        assert len(context_data["error_history"]) == 1
        assert len(context_data["learned_constraints"]) == 1
    
    def test_multiple_checkpoints(self, checkpoint_manager, sample_context):
        """Test saving multiple checkpoints."""
        checkpoint_id1 = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        time.sleep(0.01)  # Ensure different timestamps
        checkpoint_id2 = checkpoint_manager.save_checkpoint("task1", sample_context, 1)
        
        assert checkpoint_id1 != checkpoint_id2
        
        # Both should exist
        assert (checkpoint_manager.checkpoint_dir / f"{checkpoint_id1}.json").exists()
        assert (checkpoint_manager.checkpoint_dir / f"{checkpoint_id2}.json").exists()


class TestLoadCheckpoint:
    """Test checkpoint loading."""
    
    def test_load_checkpoint(self, checkpoint_manager, sample_context):
        """Test loading a checkpoint."""
        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        
        loaded_context, objective_index = checkpoint_manager.load_checkpoint(checkpoint_id)
        
        assert objective_index == 0
        assert loaded_context.objective == sample_context.objective
        assert len(loaded_context.module_results) == len(sample_context.module_results)
        assert len(loaded_context.error_history) == len(sample_context.error_history)
        assert loaded_context.learned_constraints == sample_context.learned_constraints
        assert loaded_context.accumulated_state == sample_context.accumulated_state
    
    def test_load_nonexistent_checkpoint(self, checkpoint_manager):
        """Test loading non-existent checkpoint."""
        with pytest.raises(FileNotFoundError):
            checkpoint_manager.load_checkpoint("nonexistent")
    
    def test_load_invalid_checkpoint(self, checkpoint_manager):
        """Test loading invalid checkpoint file."""
        # Create invalid checkpoint file
        invalid_path = checkpoint_manager.checkpoint_dir / "invalid.json"
        with open(invalid_path, 'w') as f:
            f.write("invalid json")
        
        with pytest.raises(ValueError):
            checkpoint_manager.load_checkpoint("invalid")


class TestGetLatestCheckpoint:
    """Test getting latest checkpoint."""
    
    def test_get_latest_checkpoint(self, checkpoint_manager, sample_context):
        """Test getting most recent checkpoint."""
        checkpoint_id1 = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        time.sleep(0.01)
        checkpoint_id2 = checkpoint_manager.save_checkpoint("task1", sample_context, 1)
        time.sleep(0.01)
        checkpoint_id3 = checkpoint_manager.save_checkpoint("task1", sample_context, 2)
        
        latest = checkpoint_manager.get_latest_checkpoint("task1")
        
        assert latest == checkpoint_id3
    
    def test_get_latest_no_checkpoints(self, checkpoint_manager):
        """Test getting latest when no checkpoints exist."""
        latest = checkpoint_manager.get_latest_checkpoint("task1")
        
        assert latest is None
    
    def test_get_latest_different_tasks(self, checkpoint_manager, sample_context):
        """Test getting latest for specific task."""
        checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        time.sleep(0.01)
        checkpoint_id2 = checkpoint_manager.save_checkpoint("task2", sample_context, 0)
        
        latest = checkpoint_manager.get_latest_checkpoint("task2")
        
        assert latest == checkpoint_id2


class TestDeleteCheckpoint:
    """Test checkpoint deletion."""
    
    def test_delete_checkpoint(self, checkpoint_manager, sample_context):
        """Test deleting a checkpoint."""
        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        checkpoint_path = checkpoint_manager.checkpoint_dir / f"{checkpoint_id}.json"
        
        assert checkpoint_path.exists()
        
        checkpoint_manager.delete_checkpoint(checkpoint_id)
        
        assert not checkpoint_path.exists()
    
    def test_delete_nonexistent_checkpoint(self, checkpoint_manager):
        """Test deleting non-existent checkpoint (should not error)."""
        checkpoint_manager.delete_checkpoint("nonexistent")  # Should not raise
    
    def test_delete_task_checkpoints(self, checkpoint_manager, sample_context):
        """Test deleting all checkpoints for a task."""
        checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        checkpoint_manager.save_checkpoint("task1", sample_context, 1)
        checkpoint_manager.save_checkpoint("task2", sample_context, 0)
        
        count = checkpoint_manager.delete_task_checkpoints("task1")
        
        assert count == 2
        assert checkpoint_manager.get_latest_checkpoint("task1") is None
        assert checkpoint_manager.get_latest_checkpoint("task2") is not None


class TestCleanup:
    """Test checkpoint cleanup."""
    
    def test_cleanup_excess_checkpoints(self, checkpoint_manager, sample_context):
        """Test cleanup of excess checkpoints."""
        # Create more than max_checkpoints (5)
        for i in range(7):
            checkpoint_manager.save_checkpoint("task1", sample_context, i)
            time.sleep(0.05)  # Longer delay to ensure distinct timestamps
        
        # Should only keep 5 most recent
        checkpoints = list(checkpoint_manager.checkpoint_dir.glob("task1_*.json"))
        assert len(checkpoints) == 5
    
    def test_cleanup_expired_checkpoints(self, checkpoint_manager, sample_context):
        """Test cleanup of expired checkpoints."""
        # Create checkpoint
        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        checkpoint_path = checkpoint_manager.checkpoint_dir / f"{checkpoint_id}.json"
        
        # Modify timestamp to be old
        old_time = time.time() - (8 * 24 * 60 * 60)  # 8 days ago
        checkpoint_path.touch()
        import os
        os.utime(checkpoint_path, (old_time, old_time))
        
        # Save new checkpoint (triggers cleanup)
        checkpoint_manager.save_checkpoint("task1", sample_context, 1)
        
        # Old checkpoint should be deleted
        assert not checkpoint_path.exists()


class TestCheckpointSize:
    """Test checkpoint size methods."""
    
    def test_get_checkpoint_size(self, checkpoint_manager, sample_context):
        """Test getting checkpoint file size."""
        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        
        size = checkpoint_manager.get_checkpoint_size(checkpoint_id)
        
        assert size > 0
        assert size < 10000  # Should be small
    
    def test_get_checkpoint_size_nonexistent(self, checkpoint_manager):
        """Test getting size of non-existent checkpoint."""
        size = checkpoint_manager.get_checkpoint_size("nonexistent")
        
        assert size == 0
    
    def test_get_total_size(self, checkpoint_manager, sample_context):
        """Test getting total size of checkpoints."""
        checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        checkpoint_manager.save_checkpoint("task1", sample_context, 1)
        
        total_size = checkpoint_manager.get_total_size()
        
        assert total_size > 0
    
    def test_get_total_size_by_task(self, checkpoint_manager, sample_context):
        """Test getting total size for specific task."""
        checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        checkpoint_manager.save_checkpoint("task2", sample_context, 0)
        
        task1_size = checkpoint_manager.get_total_size("task1")
        task2_size = checkpoint_manager.get_total_size("task2")
        total_size = checkpoint_manager.get_total_size()
        
        assert task1_size > 0
        assert task2_size > 0
        assert total_size == task1_size + task2_size


class TestSerialization:
    """Test context serialization/deserialization."""

    def test_roundtrip_serialization(self, checkpoint_manager, sample_context):
        """Test that context survives save/load roundtrip."""
        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        # Check all fields
        assert loaded_context.objective == sample_context.objective
        assert loaded_context.retry_count == sample_context.retry_count
        assert loaded_context.fallback_level == sample_context.fallback_level

        # Check module results
        assert len(loaded_context.module_results) == len(sample_context.module_results)
        for module, result in sample_context.module_results.items():
            loaded_result = loaded_context.module_results[module]
            assert loaded_result.module == result.module
            assert loaded_result.status == result.status
            assert loaded_result.output == result.output

        # Check error history
        assert len(loaded_context.error_history) == len(sample_context.error_history)
        for i, error in enumerate(sample_context.error_history):
            loaded_error = loaded_context.error_history[i]
            assert loaded_error.error_type == error.error_type
            assert loaded_error.error_message == error.error_message

        # Check constraints and state
        assert loaded_context.learned_constraints == sample_context.learned_constraints
        assert loaded_context.accumulated_state == sample_context.accumulated_state


class TestWorldStateRoundtrip:
    """Test WorldState serialization/deserialization through checkpoints."""

    def test_world_state_roundtrip(self, checkpoint_manager, sample_context):
        """Test that WorldState survives save/load roundtrip."""
        sample_context.world_state.active_app = "Notepad"
        sample_context.world_state.active_window = "Untitled - Notepad"
        sample_context.world_state.last_text_artifact = "Cats are fluffy animals."
        sample_context.world_state.app_launch_mode = "launched"
        sample_context.world_state.document_state = "fresh"
        sample_context.world_state.last_opened_url = "https://en.wikipedia.org/wiki/Cat"

        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        ws = loaded_context.world_state
        assert ws.active_app == "Notepad"
        assert ws.active_window == "Untitled - Notepad"
        assert ws.last_text_artifact == "Cats are fluffy animals."
        assert ws.app_launch_mode == "launched"
        assert ws.document_state == "fresh"
        assert ws.last_opened_url == "https://en.wikipedia.org/wiki/Cat"

    def test_world_state_is_app_open_after_roundtrip(self, checkpoint_manager, sample_context):
        """Test that is_app_open() works correctly after checkpoint roundtrip."""
        sample_context.world_state.active_app = "Notepad"
        sample_context.world_state.app_launch_mode = "launched"

        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        assert loaded_context.world_state.is_app_open("Notepad") is True
        assert loaded_context.world_state.is_app_open("Calculator") is False

    def test_old_checkpoint_without_world_state_deserializes_gracefully(
        self, checkpoint_manager, temp_checkpoint_dir
    ):
        """Old checkpoints lacking world_state key must not raise — get empty WorldState."""
        temp_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        old_data = {
            "checkpoint_id": "task1_obj0_1000",
            "task_id": "task1",
            "objective_index": 0,
            "timestamp": 1000.0,
            "context": {
                "objective": "Old objective",
                "module_results": {},
                "error_history": [],
                "learned_constraints": [],
                "accumulated_state": {},
                "retry_count": 0,
                "fallback_level": 0,
                "checkpoint_id": None,
                # NOTE: no "world_state" key — simulates pre-WorldState checkpoint
            },
        }
        checkpoint_path = temp_checkpoint_dir / "task1_obj0_1000.json"
        import json as _json
        with open(checkpoint_path, "w") as f:
            _json.dump(old_data, f)

        loaded_context, objective_index = checkpoint_manager.load_checkpoint("task1_obj0_1000")

        assert objective_index == 0
        assert loaded_context.objective == "Old objective"
        # WorldState should be empty but valid
        ws = loaded_context.world_state
        assert isinstance(ws, WorldState)
        assert ws.active_app is None
        assert ws.last_text_artifact is None
        assert ws.has_state() is False

    def test_world_state_none_fields_roundtrip(self, checkpoint_manager, sample_context):
        """Test that None WorldState fields survive roundtrip correctly."""
        # Only set some fields
        sample_context.world_state.active_app = "Chrome"
        sample_context.world_state.last_opened_url = "https://example.com"
        # active_window, last_text_artifact, etc. remain None

        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        ws = loaded_context.world_state
        assert ws.active_app == "Chrome"
        assert ws.last_opened_url == "https://example.com"
        assert ws.active_window is None
        assert ws.last_text_artifact is None
        assert ws.active_document is None
        assert ws.app_launch_mode is None
        assert ws.document_state is None

    def test_world_state_has_state_after_roundtrip(self, checkpoint_manager, sample_context):
        """Test has_state() returns True when state fields are populated after roundtrip."""
        sample_context.world_state.active_app = "Notepad"

        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        assert loaded_context.world_state.has_state() is True

    def test_empty_world_state_roundtrip(self, checkpoint_manager, sample_context):
        """Test that empty WorldState roundtrips cleanly."""
        # world_state is default-initialized, all None
        assert sample_context.world_state.has_state() is False

        checkpoint_id = checkpoint_manager.save_checkpoint("task1", sample_context, 0)
        loaded_context, _ = checkpoint_manager.load_checkpoint(checkpoint_id)

        assert loaded_context.world_state.has_state() is False
        assert loaded_context.world_state.active_app is None
