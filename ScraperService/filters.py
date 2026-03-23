import re
try:
    from rapidfuzz import fuzz
except ImportError:
    # Fallback if rapidfuzz is not installed yet
    fuzz = None

def apply_programmatic_filters(results: list, requested_part: str) -> list:
    """
    Applies fuzzy string matching and negative keyword filtering to scraped part results.
    
    Args:
        results: List of dictionaries representing scraped parts. 
                 Must contain a 'description' key.
        requested_part: The part name requested by the user.
        
    Returns:
        A filtered and sorted list of matching parts.
    """
    if not results or not requested_part:
        return results
        
    req_lower = requested_part.lower()
    filtered_results = []
    
    # Define negative keywords logic
    # Examples: If user wants "Front", exclude "Rear". If "Left", exclude "Right".
    opposites = {
        "front": "rear",
        "rear": "front",
        "left": "right",
        "right": "left",
        "upper": "lower",
        "lower": "upper",
        "inner": "outer",
        "outer": "inner",
        "driver": "passenger",
        "passenger": "driver",
        "automatic": "manual",
        "manual": "automatic"
    }
    
    negative_words = set()
    for word in req_lower.split():
        # Remove common punctuation
        clean_word = re.sub(r'[^a-z0-9]', '', word)
        if clean_word in opposites:
            negative_words.add(opposites[clean_word])
    
    for item in results:
        desc = item.get("description", "").lower()
        if not desc:
            filtered_results.append(item)
            continue
            
        # 1. Negative Keyword Filter
        has_negative = False
        for neg_word in negative_words:
            if re.search(rf'\b{neg_word}\b', desc):
                has_negative = True
                break
                
        if has_negative:
            continue
            
        # 2. Fuzzy String Matching
        if fuzz:
            score = fuzz.partial_ratio(req_lower, desc)
            token_score = fuzz.token_set_ratio(req_lower, desc)
            item["_match_score"] = max(score, token_score)
            
            # Keep if similarity is acceptable (e.g., above 60%)
            if item["_match_score"] >= 60:
                filtered_results.append(item)
        else:
            # Fallback exact word overlap match if rapidfuzz unavailable
            req_words = set(req_lower.split())
            desc_words = set(desc.split())
            overlap = req_words.intersection(desc_words)
            if float(len(overlap)) / len(req_words) > 0.4:
                item["_match_score"] = len(overlap)
                filtered_results.append(item)
            
    if fuzz or filtered_results:
        # Sort by match score descending
        filtered_results.sort(key=lambda x: x.get("_match_score", 0), reverse=True)
        
    # Clean up score temp key
    for r in filtered_results:
        r.pop("_match_score", None)
        
    return filtered_results
