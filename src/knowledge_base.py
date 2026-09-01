import re
from typing import List, Dict, Any, Set, Final
from src.logger import logger

ALLOWED_TOKENS: Final[Set[str]] = {"true", "false", "and", "or", "not", "(", ")"}


class KnowledgeBase:
    """Manages local RAG rules loaded dynamically from the SQLite database."""

    def __init__(self, db: Any) -> None:
        self.db: Any = db

    def load_rules(self) -> List[Dict[str, Any]]:
        """Loads and returns troubleshooting rules from SQLite in real-time."""
        return self.db.get_kb_rules()

    def evaluate_pattern(self, pattern: str, message: str, is_regex: bool = False) -> bool:
        """
        Evaluates a rule pattern against a log message.
        Supports both legacy substring matches, SQL-like boolean expressions, and regex.
        Example of SQL-like: ("%error out of memory%" and "%container sserr%") or ("%error out of cpu%")
        """
        msg_lower: str = message.lower()

        if is_regex:
            return self._evaluate_regex(pattern, msg_lower)

        if '"' not in pattern and "'" not in pattern:
            return pattern.lower() in msg_lower

        return self._evaluate_sql_like(pattern, msg_lower)

    @staticmethod
    def _evaluate_regex(pattern: str, msg_lower: str) -> bool:
        try:
            return bool(re.search(pattern, msg_lower))
        except re.error as err:
            logger.error(f"Error compilando regex '{pattern}': {err}")
            return False

    def _evaluate_sql_like(self, pattern: str, msg_lower: str) -> bool:
        def eval_literal(match: re.Match) -> str:
            val = match.group(1).lower()
            regex_str = "^" + re.escape(val).replace("%", ".*").replace("_", ".") + "$"
            if re.search(regex_str, msg_lower, re.DOTALL):
                return " True "
            return " False "

        expr: str = re.sub(r'"([^"]*)"', eval_literal, pattern)
        expr = re.sub(r"'([^']*)'", eval_literal, expr)
        expr = re.sub(r'(?i)\b(and|or|not)\b', lambda m: m.group(1).lower(), expr)

        tokens = re.findall(r'[a-zA-Z]+|\(|\)', expr)
        for t in tokens:
            if t.lower() not in ALLOWED_TOKENS:
                return pattern.lower() in msg_lower

        try:
            return bool(eval(expr, {"__builtins__": {}}, {}))
        except Exception as err:
            logger.error(f"Error al evaluar patrón de conocimiento '{pattern}': {err}")
            return pattern.lower() in msg_lower

    def match_logs(self, unique_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Matches unique error log messages against active patterns.
        Returns a list of matched rule definitions.
        """
        rules = self.load_rules()
        if not rules:
            return []

        matched_rules: List[Dict[str, Any]] = []
        matched_patterns: Set[str] = set()

        for log in unique_logs:
            for rule in rules:
                pattern: str = rule.get("pattern", "")
                if not pattern or pattern in matched_patterns:
                    continue

                is_regex: bool = bool(rule.get("is_regex", False))
                if self.evaluate_pattern(pattern, log["message"], is_regex):
                    matched_rules.append(rule)
                    matched_patterns.add(pattern)
                    logger.info(f"💡 [CONOCIMIENTO ENCONTRADO] El log coincide con el patrón: '{rule['pattern']}'")

        return matched_rules
