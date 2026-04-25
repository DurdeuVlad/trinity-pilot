import sys
import asyncio
import json
import argparse
import os
from pathlib import Path
from typing import Optional

# Add trinity-pilot to path
sys.path.append(str(Path(__file__).parent))

from trinity_core.trinity import TrinityExecutor
from trinity_core.config import TrinityConfig
from trinity_core.models import TaskInput

async def main():
    parser = argparse.ArgumentParser(description="Run a single Trinity task.")
    parser.add_argument("--description", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    
    args = parser.parse_args()

    # Set env vars to satisfy pydantic validation in from_env()
    os.environ["TRINITY_AI_MODEL"] = args.model
    os.environ["TRINITY_AI_PROVIDER"] = args.provider
    if args.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
    if args.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = "dummy"

    # Create custom config
    config = TrinityConfig.from_env()
    # Ensure we have keys (they should be in env already, but we can override if needed)
    
    executor = TrinityExecutor(config=config)
    
    task_input = TaskInput(
        task_id="bench-" + Path(args.output).stem,
        description=args.description,
        domain=args.domain,
        timeout=args.timeout
    )
    
    async with executor:
        result = await executor.execute(task_input)
        
    # Serialize result
    result_dict = result.model_dump()
    
    with open(args.output, 'w') as f:
        json.dump(result_dict, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
