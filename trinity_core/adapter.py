"""Abstract base class for Trinity module adapters."""
from abc import ABC, abstractmethod
from typing import Dict
from .models import TaskInput, TaskResult

class TaskAdapter(ABC):
    """Abstract base class for Trinity module adapters."""
    
    @abstractmethod
    async def execute(self, task: TaskInput) -> TaskResult:
        """
        Execute a task using the underlying module.
        
        Args:
            task: Unified task input
            
        Returns:
            Unified task result
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the module is available and functional."""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> Dict:
        """Return module capabilities and constraints."""
        pass
