"""Inspect raw response from a reasoner model to check for thinking content."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import os
import json

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI()


async def main():
    response = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "deepseek-reasoner"),
        messages=[{"role": "user", "content": "1+1=?"}],
    )
    choice = response.choices[0].message
    dumped = choice.model_dump(exclude_none=True)

    print("=== Fields in response ===")
    for key in dumped:
        print(f"  {key}: {type(dumped[key]).__name__}")

    print("\n=== Full dump ===")
    print(json.dumps(dumped, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
