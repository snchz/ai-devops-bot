import os
import json
from typing import List, Dict, Any
from src.logger import logger

class KnowledgeBase:
    """Manages local RAG rules loaded dynamically from a JSON file."""
    
    def __init__(self, path: str):
        self.path = path
        
    def load_rules(self) -> List[Dict[str, Any]]:
        """Loads and returns troubleshooting rules from JSON file in real-time."""
        if not os.path.exists(self.path):
            logger.debug(f"Base de conocimientos {self.path} no encontrada. Retornando lista vacía.")
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer base de conocimientos en {self.path}: {e}")
            return []
            
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
