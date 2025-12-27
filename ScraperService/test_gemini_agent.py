"""
Test Gemini AI Agent Integration
================================

Run this test to verify the Gemini AI agent is working correctly.

Usage:
    cd ScraperService
    set GEMINI_API_KEY=your-api-key
    python test_gemini_agent.py
"""

import asyncio
import os
import sys

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gemini_agent import GeminiVisionAgent


async def test_keyword_expansion():
    """Test AI-powered keyword expansion for job descriptions."""
    print("=" * 60)
    print("GEMINI AI AGENT - KEYWORD EXPANSION TEST")
    print("=" * 60)
    
    # Get API key - use environment variable or default
    api_key = os.getenv("GEMINI_API_KEY", "AIzaSyDTXqRjf6AjOsftTfYv5t05koE3SpVV1MM")
    if not api_key:
        print("\n[ERROR] Set GEMINI_API_KEY environment variable")
        print("   Example: set GEMINI_API_KEY=AIzaSyDTXqRjf6AjOsftTfYv5t05koE3SpVV1MM")
        return False
    
    # Initialize agent
    print(f"\n[INIT] Initializing agent with key: {api_key[:10]}...")
    agent = GeminiVisionAgent(api_key)
    
    if not agent.initialized:
        print("[ERROR] Agent initialization failed!")
        return False
    
    print("[OK] Agent initialized successfully!")
    
    # Test cases
    test_jobs = [
        "Oil Change Service",
        "Brake Pad Replacement",
        "Air Conditioner Not Working",
        "Engine Overheating",
        "Battery Replacement"
    ]
    
    print("\n" + "-" * 60)
    print("KEYWORD EXPANSION TESTS")
    print("-" * 60)
    
    all_passed = True
    for job in test_jobs:
        print(f"\n[JOB] '{job}'")
        try:
            keywords = await agent.get_search_keywords(job)
            print(f"   [KEYWORDS] {keywords}")
            
            if not keywords or len(keywords) == 0:
                print(f"   [WARNING] No keywords returned!")
                all_passed = False
        except Exception as e:
            print(f"   [ERROR] {e}")
            all_passed = False
    
    # Test caching
    print("\n" + "-" * 60)
    print("CACHE TEST")
    print("-" * 60)
    print("\n[CACHE] Testing cache (repeat 'Oil Change Service')...")
    keywords2 = await agent.get_search_keywords("Oil Change Service")
    print(f"   [KEYWORDS] {keywords2}")
    
    # Show stats
    stats = agent.get_stats()
    print("\n" + "-" * 60)
    print("STATISTICS")
    print("-" * 60)
    print(f"   API Calls: {stats['api_calls']}")
    print(f"   Cache Hits: {stats['cache_hits']}")
    print(f"   Avg Latency: {stats['avg_latency_ms']}ms")
    print(f"   Cache Size: {stats['cache_size']}")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] ALL TESTS PASSED!")
    else:
        print("[WARNING] SOME TESTS HAD ISSUES")
    print("=" * 60)
    
    return all_passed


async def test_vision_with_screenshot():
    """Test vision-based element detection (requires a screenshot)."""
    print("\n" + "=" * 60)
    print("GEMINI AI AGENT - VISION TEST (Optional)")
    print("=" * 60)
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return
    
    agent = GeminiVisionAgent(api_key)
    if not agent.initialized:
        return
    
    # Check if we have pyautogui for screenshots
    try:
        import pyautogui
        print("\n[SCREENSHOT] Taking screenshot...")
        screenshot = pyautogui.screenshot()
        
        print("[AI] Asking AI to find 'any input field or text box'...")
        result = await agent.find_element(screenshot, "any input field or text box")
        
        if result.get("success"):
            print(f"   [FOUND] at ({result['x']}, {result['y']})")
            print(f"   [CONFIDENCE] {result['confidence']:.2f}")
            print(f"   [REASONING] {result.get('reasoning', 'N/A')}")
        else:
            print(f"   [NOT FOUND] {result.get('error', 'Unknown')}")
            
    except ImportError:
        print("\n[SKIP] pyautogui not available - skipping vision test")
    except Exception as e:
        print(f"\n[ERROR] Vision test error: {e}")


if __name__ == "__main__":
    print("\n[AI] GEMINI AI AGENT TEST SUITE\n")
    
    # Run tests
    asyncio.run(test_keyword_expansion())
    asyncio.run(test_vision_with_screenshot())
    
    print("\n[DONE] Test complete!")
