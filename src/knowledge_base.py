import re
from typing import List, Dict, Any
from src.logger import logger

class KnowledgeBase:
    """Manages local RAG rules loaded dynamically from the SQLite database."""
    
    def __init__(self, db):
        self.db = db
        
    def load_rules(self) -> List[Dict[str, Any]]:
        """Loads and returns troubleshooting rules from SQLite in real-time."""
        return self.db.get_kb_rules()
        
    def evaluate_pattern(self, pattern: str, message: str) -> bool:
        """
        Evaluates a rule pattern against a log message.
        Supports both legacy substring matches and SQL-like boolean expressions.
        Example of SQL-like: ("%error out of memory%" and "%container sserr%") or ("%error out of cpu%")
        """
        if '"' not in pattern and "'" not in pattern:
            # Fallback to legacy substring match
            return pattern.lower() in message.lower()
            
        msg_lower = message.lower()
        
        def eval_literal(match):
            val = match.group(1).lower()
            # Convert SQL LIKE wildcards to regex
            regex_str = "^" + re.escape(val).replace("%", ".*").replace("_", ".") + "$"
            if re.search(regex_str, msg_lower, re.DOTALL):
                return " True "
            return " False "
            
        # Replace string literals with " True " or " False "
        expr = re.sub(r'"([^"]*)"', eval_literal, pattern)
        expr = re.sub(r"'([^']*)'", eval_literal, expr)
        
        # Normalize boolean operators to lowercase
        expr = re.sub(r'(?i)\b(and|or|not)\b', lambda m: m.group(1).lower(), expr)
        
        # Tokenize to ensure no malicious code is executed
        tokens = re.findall(r'[a-zA-Z]+|\(|\)', expr)
        allowed_tokens = {"true", "false", "and", "or", "not", "(", ")"}
        for t in tokens:
            if t.lower() not in allowed_tokens:
                # Unexpected token, fallback to legacy
                return pattern.lower() in msg_lower
                
        try:
            # Safe evaluation
            return bool(eval(expr, {"__builtins__": {}}, {}))
        except Exception as e:
            logger.error(f"Error al evaluar patrón de conocimiento '{pattern}': {e}")
            return pattern.lower() in msg_lower

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
            for rule in rules:
                pattern = rule.get("pattern", "")
                if not pattern:
                    continue
                # Use the new evaluation function
                if pattern not in matched_patterns and self.evaluate_pattern(pattern, log["message"]):
                    matched_rules.append(rule)
                    matched_patterns.add(pattern)
                    logger.info(f"💡 [CONOCIMIENTO ENCONTRADO] El log coincide con el patrón: '{rule['pattern']}'")
                    
        return matched_rules
