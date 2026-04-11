"""Unified configuration for Trinity integration."""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import os

class ModuleConfig(BaseModel):
    """Configuration for a specific module."""
    enabled: bool = Field(True, description="Enable this module")
    timeout: int = Field(300, ge=30, le=3600, description="Timeout in seconds")
    max_retries: int = Field(3, ge=0, le=10, description="Max retry attempts")

class BrowserConfig(ModuleConfig):
    """Browser-specific configuration."""
    headless: bool = Field(False, description="Run browser in headless mode")
    browser_type: str = Field("chromium", description="Browser type (chromium, firefox, webkit)")
    viewport_width: int = Field(1920, ge=800, le=3840, description="Viewport width")
    viewport_height: int = Field(1080, ge=600, le=2160, description="Viewport height")
    timeout: int = Field(600, ge=30, le=3600)  # Browser needs longer timeout

class DesktopConfig(ModuleConfig):
    """Desktop-specific configuration."""
    default_app: Optional[str] = Field(None, description="Default target application")
    timeout: int = Field(600, ge=30, le=3600)

class CLIConfig(ModuleConfig):
    """CLI-specific configuration."""
    shell: str = Field("powershell", description="Shell to use (powershell, cmd)")
    allow_dangerous: bool = Field(False, description="Allow potentially destructive commands")
    timeout: int = Field(300, ge=30, le=1800)

class TrinityConfig(BaseModel):
    """Unified configuration for all Trinity modules."""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "gemini_api_key": "YOUR_API_KEY",
                "debug_mode": False,
                "flight_reports_dir": "_runtime/flight_reports"
            }
        }
    )

    # Global settings
    gemini_api_key: str = Field(..., description="Gemini API key (required)")
    debug_mode: bool = Field(False, description="Enable debug logging")
    flight_reports_dir: str = Field("_runtime/flight_reports", description="FlightReport output directory")
    
    # Executor settings
    max_concurrent_browser_tasks: int = Field(5, ge=1, le=20, description="Max parallel browser tasks")

    # Runtime layer - set True to route tasks through Architect-Executor-Reviewer runtimes.
    # Defaults to False to preserve backward-compatible adapter-direct execution.
    enable_runtimes: bool = Field(False, description="Enable tool-first runtime orchestration layer")
    
    # Module-specific configs
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)
    cli: CLIConfig = Field(default_factory=CLIConfig)
    
    @field_validator("gemini_api_key")
    @classmethod
    def validate_api_key(cls, v):
        """Ensure API key is not empty."""
        if not v or v.strip() == "":
            raise ValueError("GEMINI_API_KEY is required and cannot be empty")
        return v
    
    @classmethod
    def from_env(cls, env_prefix: str = "TRINITY") -> "TrinityConfig":
        """
        Load configuration from environment variables.
        """
        return cls(
            # Required
            gemini_api_key=os.getenv(f"{env_prefix}_GEMINI_API_KEY", 
                                    os.getenv("GEMINI_API_KEY", "")),
            
            # Global
            debug_mode=os.getenv(f"{env_prefix}_DEBUG", "false").lower() == "true",
            flight_reports_dir=os.getenv(f"{env_prefix}_FLIGHT_REPORTS_DIR", 
                                         "_runtime/flight_reports"),
            max_concurrent_browser_tasks=int(os.getenv(f"{env_prefix}_MAX_CONCURRENT_BROWSER", "5")),
            
            # Browser
            browser=BrowserConfig(
                enabled=os.getenv(f"{env_prefix}_BROWSER_ENABLED", "true").lower() == "true",
                headless=os.getenv(f"{env_prefix}_BROWSER_HEADLESS", "false").lower() == "true",
                browser_type=os.getenv(f"{env_prefix}_BROWSER_TYPE", "chromium"),
                timeout=int(os.getenv(f"{env_prefix}_BROWSER_TIMEOUT", "600")),
                max_retries=int(os.getenv(f"{env_prefix}_BROWSER_MAX_RETRIES", "3"))
            ),
            
            # Desktop
            desktop=DesktopConfig(
                enabled=os.getenv(f"{env_prefix}_DESKTOP_ENABLED", "true").lower() == "true",
                default_app=os.getenv(f"{env_prefix}_DESKTOP_DEFAULT_APP"),
                timeout=int(os.getenv(f"{env_prefix}_DESKTOP_TIMEOUT", "600")),
                max_retries=int(os.getenv(f"{env_prefix}_DESKTOP_MAX_RETRIES", "3"))
            ),
            
            # CLI
            cli=CLIConfig(
                enabled=os.getenv(f"{env_prefix}_CLI_ENABLED", "true").lower() == "true",
                shell=os.getenv(f"{env_prefix}_CLI_SHELL", "powershell"),
                allow_dangerous=os.getenv(f"{env_prefix}_CLI_ALLOW_DANGEROUS", "false").lower() == "true",
                timeout=int(os.getenv(f"{env_prefix}_CLI_TIMEOUT", "300")),
                max_retries=int(os.getenv(f"{env_prefix}_CLI_MAX_RETRIES", "2"))
            )
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return self.model_dump()
    
    def save_to_file(self, path: str):
        """Save configuration to JSON file."""
        import json
        with open(path, 'w') as f:
            json.dump(self.model_dump(), f, indent=2)
    
    @classmethod
    def load_from_file(cls, path: str) -> "TrinityConfig":
        """Load configuration from JSON file."""
        import json
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(**data)
