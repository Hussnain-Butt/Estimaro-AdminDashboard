"""
Gemini AI Agent for Intelligent Automation
==========================================

This module provides AI-powered capabilities for the Estimaro Scraper:
1. Vision-based element detection - Find UI elements from screenshots
2. Smart keyword matching - Expand job descriptions into search terms
3. Self-healing automation - Analyze failures and suggest fixes

Usage:
    from gemini_agent import GeminiVisionAgent
    agent = GeminiVisionAgent(api_key="your-gemini-api-key")
    
    # Find element on screen
    result = await agent.find_element(screenshot, "VIN input field")
    
    # Get search keywords
    keywords = await agent.get_search_keywords("Oil Change Service")
    
    # Analyze automation failure
    fix = await agent.analyze_failure(screenshot, "Checkbox not found")
"""

import logging
import base64
import io
import json
import asyncio
from typing import Optional, List, Dict, Tuple
from functools import lru_cache
import time

# Try to import Google Generative AI
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

# Try to import PIL for image handling
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None

logger = logging.getLogger(__name__)


class GeminiVisionAgent:
    """
    AI agent for intelligent UI automation using Google Gemini Vision API.
    
    Features:
    - Find UI elements by describing them (returns x, y coordinates)
    - Expand job descriptions into multiple search keywords
    - Analyze automation failures and suggest fixes
    - Built-in caching to reduce API costs
    """
    
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        """
        Initialize the Gemini Vision Agent.
        
        Args:
            api_key: Your Gemini API key
            model_name: Model to use (default: gemini-2.0-flash for vision)
        """
        self.api_key = api_key
        self.model_name = model_name
        self.model = None
        self.initialized = False
        
        # Cache for keyword expansions (job_description -> keywords)
        self._keyword_cache: Dict[str, List[str]] = {}
        
        # Stats for monitoring
        self.stats = {
            "api_calls": 0,
            "cache_hits": 0,
            "total_latency_ms": 0
        }
        
        if not GEMINI_AVAILABLE:
            logger.warning("Gemini AI not available - install google-generativeai package")
            return
            
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
            self.initialized = True
            logger.info(f"✅ Gemini AI Agent initialized with model: {model_name}")
        except Exception as e:
            logger.error(f"❌ Gemini AI initialization failed: {e}")
    
    def _log(self, message: str, level: str = "info"):
        """Log with [AI] prefix."""
        formatted = f"[AI] {message}"
        if level == "error":
            logger.error(formatted)
        elif level == "warning":
            logger.warning(formatted)
        else:
            logger.info(formatted)
        print(formatted)
    
    def _image_to_base64(self, image) -> str:
        """Convert PIL Image to base64 string."""
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL not available for image encoding")
        
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    async def find_element(self, screenshot, description: str) -> Dict:
        """
        Find a UI element by describing what to look for.
        
        Args:
            screenshot: PIL Image or path to screenshot
            description: What to find (e.g., "VIN input field", "Price button")
            
        Returns:
            {
                "success": bool,
                "x": int,          # X coordinate to click
                "y": int,          # Y coordinate to click
                "confidence": float,  # 0.0-1.0 confidence score
                "reasoning": str   # Why AI chose this location
            }
        """
        if not self.initialized:
            return {"success": False, "error": "Gemini AI not initialized"}
        
        start_time = time.time()
        
        try:
            self._log(f"Finding element: '{description}'")
            
            # Load image if path provided
            if isinstance(screenshot, str):
                screenshot = Image.open(screenshot)
            
            # Prepare the prompt
            prompt = f"""You are a UI automation expert. Look at this screenshot and find the element described.

ELEMENT TO FIND: {description}

Analyze the screenshot and respond with ONLY a JSON object (no markdown, no explanation):
{{
    "found": true/false,
    "x": <x coordinate of center of element>,
    "y": <y coordinate of center of element>,
    "confidence": <0.0-1.0>,
    "reasoning": "<brief explanation of what you found>"
}}

If you cannot find the element, set found=false and explain why in reasoning.
The coordinates should be the CENTER of the element you found.
"""
            
            # Send to Gemini Vision
            response = self.model.generate_content([
                prompt,
                screenshot
            ])
            
            # Parse response
            response_text = response.text.strip()
            
            # Clean up response if it has markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            # Update stats
            self.stats["api_calls"] += 1
            latency = int((time.time() - start_time) * 1000)
            self.stats["total_latency_ms"] += latency
            
            if result.get("found"):
                self._log(f"Found at ({result['x']}, {result['y']}) confidence={result['confidence']:.2f} ({latency}ms)")
                return {
                    "success": True,
                    "x": int(result["x"]),
                    "y": int(result["y"]),
                    "confidence": float(result["confidence"]),
                    "reasoning": result.get("reasoning", "")
                }
            else:
                self._log(f"Element not found: {result.get('reasoning', 'Unknown')}", "warning")
                return {
                    "success": False,
                    "error": result.get("reasoning", "Element not found"),
                    "confidence": 0.0
                }
                
        except json.JSONDecodeError as e:
            self._log(f"Failed to parse AI response: {e}", "error")
            return {"success": False, "error": f"Invalid AI response: {e}"}
        except Exception as e:
            self._log(f"find_element error: {e}", "error")
            return {"success": False, "error": str(e)}
    
    async def get_search_keywords(self, job_description: str) -> List[str]:
        """
        Expand a job description into multiple search keywords.
        
        Args:
            job_description: User's job description (e.g., "Oil Change Service")
            
        Returns:
            List of keywords to try (e.g., ["Oil", "Engine Oil", "Lubrication", "Filter"])
        """
        # Check cache first
        cache_key = job_description.lower().strip()
        if cache_key in self._keyword_cache:
            self.stats["cache_hits"] += 1
            self._log(f"Keywords from cache: {self._keyword_cache[cache_key]}")
            return self._keyword_cache[cache_key]
        
        if not self.initialized:
            # Fallback: return first word
            return [job_description.split()[0]] if job_description else []
        
        start_time = time.time()
        
        try:
            self._log(f"Generating keywords for: '{job_description}'")
            
            prompt = f"""You are an automotive parts expert. Given a job description, generate search keywords that would find relevant parts in an auto parts catalog.

JOB DESCRIPTION: {job_description}

Generate 3-5 simple keywords that would help find parts for this job in a vendor catalog like Worldpac or SSF.

Rules:
- Use simple, common terms (not technical jargon)
- Start with the most specific keyword, then get more general
- Include component names that might be replaced during this job

Respond with ONLY a JSON array of strings (no explanation):
["keyword1", "keyword2", "keyword3"]

Example for "Oil Change Service": ["Oil", "Engine Oil", "Oil Filter", "Drain Plug"]
Example for "Brake squeaking": ["Brake Pad", "Brake", "Rotor", "Caliper"]
"""
            
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean markdown if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            keywords = json.loads(response_text)
            
            # Ensure it's a list of strings
            if isinstance(keywords, list):
                keywords = [str(k) for k in keywords[:5]]  # Max 5 keywords
            else:
                keywords = [job_description.split()[0]]
            
            # Cache the result
            self._keyword_cache[cache_key] = keywords
            
            # Update stats
            self.stats["api_calls"] += 1
            latency = int((time.time() - start_time) * 1000)
            self.stats["total_latency_ms"] += latency
            
            self._log(f"Keywords: {keywords} ({latency}ms)")
            return keywords
            
        except Exception as e:
            self._log(f"get_search_keywords error: {e}", "error")
            # Fallback: return first word
            return [job_description.split()[0]] if job_description else []
    
    async def analyze_failure(self, screenshot, error: str, context: str = "") -> Dict:
        """
        Analyze why an automation step failed and suggest a fix.
        
        Args:
            screenshot: PIL Image of current screen state
            error: The error message or description of what failed
            context: Additional context about what we were trying to do
            
        Returns:
            {
                "diagnosis": str,      # What went wrong
                "retry_strategy": str, # How to fix it
                "new_coords": {"x": int, "y": int} or None,  # If applicable
                "should_retry": bool   # Whether retry is likely to help
            }
        """
        if not self.initialized:
            return {
                "diagnosis": "AI not available",
                "retry_strategy": "Use default fallback",
                "new_coords": None,
                "should_retry": False
            }
        
        start_time = time.time()
        
        try:
            self._log(f"Analyzing failure: '{error}'")
            
            # Load image if path provided
            if isinstance(screenshot, str):
                screenshot = Image.open(screenshot)
            
            prompt = f"""You are a UI automation debugging expert. An automation script failed and we need to understand why.

ERROR: {error}
CONTEXT: {context}

Look at the screenshot and analyze:
1. What is the current state of the UI?
2. Why might the automation have failed?
3. How can we recover or retry?

Respond with ONLY a JSON object:
{{
    "diagnosis": "<what went wrong>",
    "retry_strategy": "<how to fix it>",
    "new_coords": {{"x": <int>, "y": <int>}} or null,
    "should_retry": true/false
}}

If you can see where we should click instead, provide new_coords.
"""
            
            response = self.model.generate_content([
                prompt,
                screenshot
            ])
            
            response_text = response.text.strip()
            
            # Clean markdown if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            # Update stats
            self.stats["api_calls"] += 1
            latency = int((time.time() - start_time) * 1000)
            self.stats["total_latency_ms"] += latency
            
            self._log(f"Diagnosis: {result.get('diagnosis', 'Unknown')} ({latency}ms)")
            
            return {
                "diagnosis": result.get("diagnosis", "Unknown failure"),
                "retry_strategy": result.get("retry_strategy", "No suggestion"),
                "new_coords": result.get("new_coords"),
                "should_retry": result.get("should_retry", False)
            }
            
        except Exception as e:
            self._log(f"analyze_failure error: {e}", "error")
            return {
                "diagnosis": str(e),
                "retry_strategy": "Use default fallback",
                "new_coords": None,
                "should_retry": False
            }
    
    def get_stats(self) -> Dict:
        """Get usage statistics."""
        avg_latency = 0
        if self.stats["api_calls"] > 0:
            avg_latency = self.stats["total_latency_ms"] / self.stats["api_calls"]
        
        return {
            **self.stats,
            "avg_latency_ms": int(avg_latency),
            "cache_size": len(self._keyword_cache),
            "initialized": self.initialized,
            "model": self.model_name
        }
    
    def clear_cache(self):
        """Clear the keyword cache."""
        self._keyword_cache.clear()
        self._log("Keyword cache cleared")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_agent: Optional[GeminiVisionAgent] = None


def get_agent(api_key: str = None) -> GeminiVisionAgent:
    """Get or create the default AI agent instance."""
    global _default_agent
    
    if _default_agent is None and api_key:
        _default_agent = GeminiVisionAgent(api_key)
    
    return _default_agent


def set_agent(agent: GeminiVisionAgent):
    """Set the default AI agent instance."""
    global _default_agent
    _default_agent = agent


# =============================================================================
# TEST
# =============================================================================
if __name__ == "__main__":
    import asyncio
    import os
    
    async def test_agent():
        print("=" * 60)
        print("GEMINI AI AGENT TEST")
        print("=" * 60)
        
        # Get API key from environment
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Set GEMINI_API_KEY environment variable to test")
            return
        
        agent = GeminiVisionAgent(api_key)
        
        if not agent.initialized:
            print("Agent failed to initialize")
            return
        
        print("\n--- Test 1: Keyword Expansion ---")
        keywords = await agent.get_search_keywords("Oil Change Service")
        print(f"Keywords: {keywords}")
        
        print("\n--- Test 2: Cache Hit ---")
        keywords2 = await agent.get_search_keywords("oil change service")  # Same, different case
        print(f"Cached Keywords: {keywords2}")
        
        print("\n--- Test 3: Different Job ---")
        keywords3 = await agent.get_search_keywords("Brake Pad Replacement")
        print(f"Keywords: {keywords3}")
        
        print("\n--- Stats ---")
        print(agent.get_stats())
        
        print("=" * 60)
    
    asyncio.run(test_agent())
