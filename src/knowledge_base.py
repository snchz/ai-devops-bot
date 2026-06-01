from typing import List, Dict, Any
from src.logger import logger

class KnowledgeBase:
    """Manages local RAG rules loaded dynamically from the SQLite database."""
    
    def __init__(self, db):
        self.db = db
        
    def load_rules(self) -> List[Dict[str, Any]]:
        """Loads and returns troubleshooting rules from SQLite in real-time."""
        return self.db.get_kb_rules()
            
    def match_logs(self, unique_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Matches unique error log messages against active patterns.
        Returns a list of matched rule definitions.
        """
        rules = self.load_rules()
        if not rules:
            return []
            
        matched_rules = []
        matched_patterns = set()
        
        for log in unique_logs:
            msg_lower = log["message"].lower()
            for rule in rules:
                pattern = rule.get("pattern", "").lower()
                if not pattern:
                    continue
                # If substring matches and hasn't been matched yet in this cycle
                if pattern in msg_lower and pattern not in matched_patterns:
                    matched_rules.append(rule)
                    matched_patterns.add(pattern)
                    logger.info(f"💡 [CONOCIMIENTO ENCONTRADO] El log coincide con el patrón: '{rule['pattern']}'")
                    
        return matched_rules
