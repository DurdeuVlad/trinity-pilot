import os
import sys
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages lifecycle of the three module services."""
    
    def __init__(self):
        self.desktop_process: Optional[subprocess.Popen] = None
        self.cli_process: Optional[subprocess.Popen] = None
        self.browser_process: Optional[subprocess.Popen] = None
        
        self.project_root = Path(__file__).parent.parent.parent
        self.desktop_script = self.project_root / "api-accessibility-poc" / "desktop_module_service.py"
        self.cli_script = self.project_root / "cli-automation-poc" / "cli_module_service.py"
        self.browser_script = self.project_root / "browser-gui-automation" / "browser_module_service.py"
        
        self.desktop_port = int(os.getenv("DESKTOP_SERVICE_PORT", "8101"))
        self.cli_port = int(os.getenv("CLI_SERVICE_PORT", "8102"))
        self.browser_port = int(os.getenv("BROWSER_SERVICE_PORT", "8103"))
    
    def start_all(self, max_wait_per_service: float = 10.0) -> bool:
        """
        Start all three module services and wait for health checks.
        
        Args:
            max_wait_per_service: Maximum seconds to wait for each service to be ready
            
        Returns:
            True if all services started successfully, False otherwise
        """
        logger.info("Starting module services...")
        
        services = [
            ("Desktop", self.desktop_script, self.desktop_port, "desktop_process"),
            ("CLI", self.cli_script, self.cli_port, "cli_process"),
            ("Browser", self.browser_script, self.browser_port, "browser_process")
        ]
        
        for name, script, port, attr_name in services:
            if not script.exists():
                logger.error(f"{name} service script not found: {script}")
                return False
            
            logger.info(f"Starting {name} service on port {port}...")
            try:
                process = subprocess.Popen(
                    [sys.executable, str(script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=script.parent
                )
                setattr(self, attr_name, process)
                
                if not self._wait_for_health(name, port, max_wait_per_service):
                    logger.error(f"{name} service failed to start")
                    return False
                
                logger.info(f"{name} service ready on port {port}")
                
            except Exception as e:
                logger.error(f"Failed to start {name} service: {e}", exc_info=True)
                return False
        
        logger.info("All module services started successfully")
        return True
    
    def _wait_for_health(self, name: str, port: int, max_wait: float) -> bool:
        """Poll health endpoint until ready or timeout."""
        url = f"http://127.0.0.1:{port}/health"
        deadline = time.monotonic() + max_wait
        
        while time.monotonic() < deadline:
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        
        return False
    
    def stop_all(self):
        """Stop all running module services."""
        logger.info("Stopping module services...")
        
        for name, attr_name in [
            ("Desktop", "desktop_process"),
            ("CLI", "cli_process"),
            ("Browser", "browser_process")
        ]:
            process = getattr(self, attr_name)
            if process:
                logger.info(f"Stopping {name} service...")
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"{name} service did not terminate, killing...")
                    process.kill()
                setattr(self, attr_name, None)
        
        logger.info("All module services stopped")
    
    def health_check_all(self) -> dict:
        """
        Check health of all three module services.
        
        Returns:
            dict with service names as keys and health status as values
        """
        results = {}
        
        for name, port in [
            ("desktop", self.desktop_port),
            ("cli", self.cli_port),
            ("browser", self.browser_port)
        ]:
            url = f"http://127.0.0.1:{port}/health"
            try:
                response = httpx.get(url, timeout=2.0)
                results[name] = {
                    "status": "ok" if response.status_code == 200 else "error",
                    "data": response.json() if response.status_code == 200 else None
                }
            except Exception as e:
                results[name] = {
                    "status": "unavailable",
                    "error": str(e)
                }
        
        return results
