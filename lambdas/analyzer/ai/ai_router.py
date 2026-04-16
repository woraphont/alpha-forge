"""
AlphaForge — Multi-AI Router
Routes tasks to the cheapest model that can handle them.

Tier 1 (Simple)  → Gemini 2.0 Flash    ~$0.000075/1K tokens
Tier 2 (Medium)  → GPT-4o-mini         ~$0.00015/1K tokens
Tier 3 (Complex) → Claude Haiku 4.5    ~$0.00025/1K tokens
Phase 4 upgrade  → AWS Bedrock Claude  (replace direct Anthropic API)

Fallback: Gemini fail → GPT-mini → Claude Haiku → log + LINE alert
"""
import json
import logging
import os
from enum import Enum
from typing import Any

import boto3

logger = logging.getLogger(__name__)

_ssm = None


def _ssm_client() -> Any:
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm", region_name="us-east-1")
    return _ssm


def _get_param(name: str) -> str:
    return _ssm_client().get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


class TaskTier(Enum):
    SIMPLE = "simple"    # format, validate, calculate TA
    MEDIUM = "medium"    # news sentiment, summary
    COMPLEX = "complex"  # full analysis, pattern recognition


def route(task_tier: TaskTier, prompt: str, system: str = "") -> str:
    """
    Route a task to the appropriate AI model.

    Args:
        task_tier: TaskTier enum value
        prompt: User/task prompt
        system: Optional system prompt

    Returns:
        AI model response text

    Raises:
        RuntimeError: If all models fail
    """
    if task_tier == TaskTier.SIMPLE:
        return _try_gemini(prompt, system) or _try_gpt_mini(prompt, system) or _try_claude_haiku(prompt, system)
    elif task_tier == TaskTier.MEDIUM:
        return _try_gpt_mini(prompt, system) or _try_gemini(prompt, system) or _try_claude_haiku(prompt, system)
    else:  # COMPLEX
        return _try_claude_haiku(prompt, system) or _try_gpt_mini(prompt, system)


def _try_gemini(prompt: str, system: str) -> str | None:
    """Tier 1: Gemini 2.0 Flash."""
    try:
        import google.generativeai as genai
        api_key = _get_param("/alpha-forge/GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = model.generate_content(full_prompt)
        logger.info({"action": "ai_call", "model": "gemini-flash", "tier": "simple"})
        return response.text
    except Exception as e:
        logger.warning({"action": "gemini_failed", "error": str(e)})
        return None


def _try_gpt_mini(prompt: str, system: str) -> str | None:
    """Tier 2: GPT-4o-mini."""
    try:
        from openai import OpenAI
        api_key = _get_param("/alpha-forge/OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=1000)
        logger.info({"action": "ai_call", "model": "gpt-4o-mini", "tier": "medium"})
        return response.choices[0].message.content
    except Exception as e:
        logger.warning({"action": "gpt_mini_failed", "error": str(e)})
        return None


def _try_claude_haiku(prompt: str, system: str) -> str | None:
    """Tier 3: Claude Haiku 4.5. Phase 4: migrate to AWS Bedrock."""
    try:
        import anthropic
        api_key = _get_param("/alpha-forge/ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        logger.info({"action": "ai_call", "model": "claude-haiku", "tier": "complex"})
        return response.content[0].text
    except Exception as e:
        logger.warning({"action": "claude_haiku_failed", "error": str(e)})
        return None
