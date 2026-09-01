import sqlite3
import json
import time
import os
import re
from typing import List, Dict, Any, Optional
from src.logger import logger

class Database:
    """Manages local SQLite database for consolidated incident tracking and RAG Knowledge Base rules."""
    
    def __init__(self, db_path: str = "history.db"):
        self.db_path = db_path

        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception:
                logger.warning(f"⚠️ No se pudo crear el directorio para la DB: {db_dir}")

        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Helper to create optimized SQLite connections with optimal PRAGMAs."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        # High performance and low disk-wear PRAGMAs
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA cache_size = -2000;")  # 2MB RAM cache limit
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.close()
        return conn

    def init_db(self):
        """Initializes database schema if it does not exist, migrating if necessary."""
        try:
            db_dir = os.path.dirname(self.db_path) or os.getcwd()
            try:
                testfile = os.path.join(db_dir, ".db_write_test")
                with open(testfile, "w", encoding="utf-8") as tf:
                    tf.write("")
                os.remove(testfile)
            except Exception:
                logger.warning(f"⚠️ No se detecta permiso de escritura en '{db_dir}'. Intentando abrir la DB de todas formas...")

            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if old table exists and needs migration
                cursor.execute("PRAGMA table_info(incidents)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if columns and "incident_num" not in columns:
                    logger.warning("⚠️ Detectada estructura de base de datos antigua. Recreando tabla para Fase 2...")
                    cursor.execute("DROP TABLE IF EXISTS incidents")
                    conn.commit()
                
                # Create incidents table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        incident_num TEXT UNIQUE NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ABIERTA',
                        apps TEXT NOT NULL,
                        error_signature TEXT UNIQUE NOT NULL,
                        logs TEXT NOT NULL,
                        matched_rules TEXT NOT NULL,
                        ai_proposal TEXT NOT NULL,
                        kb_applied TEXT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        history TEXT NOT NULL DEFAULT '[]',
                        occurrences_count INTEGER NOT NULL DEFAULT 1
                    )
                """)
                
                # Add occurrences_count column if migrating from previous schema
                cursor.execute("PRAGMA table_info(incidents)")
                cols = [c[1] for c in cursor.fetchall()]
                if cols and "occurrences_count" not in cols:
                    cursor.execute("ALTER TABLE incidents ADD COLUMN occurrences_count INTEGER NOT NULL DEFAULT 1")
                    conn.commit()
                
                # Create knowledge base rules table (kb_rules)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS kb_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pattern TEXT UNIQUE NOT NULL,
                        description TEXT,
                        cause TEXT,
                        solution TEXT NOT NULL,
                        commands TEXT,
                        action TEXT DEFAULT 'ALERT',
                        is_regex INTEGER DEFAULT 0
                    )
                """)
                
                cursor.execute("PRAGMA table_info(kb_rules)")
                columns_kb = [col[1] for col in cursor.fetchall()]
                if columns_kb and "action" not in columns_kb:
                    cursor.execute("ALTER TABLE kb_rules ADD COLUMN action TEXT DEFAULT 'ALERT'")
                    conn.commit()
                    
                if columns_kb and "is_regex" not in columns_kb:
                    cursor.execute("ALTER TABLE kb_rules ADD COLUMN is_regex INTEGER DEFAULT 0")
                    conn.commit()
                
                # Create settings table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                """)
                conn.commit()
            
            self._migrate_and_consolidate_signatures()
            logger.info(f"💾 Base de datos SQLite optimizada (WAL + Cache) inicializada en: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Error al inicializar la base de datos SQLite en '{self.db_path}': {e}", exc_info=True)

    def _migrate_and_consolidate_signatures(self):
        """Migrates and compacts large existing histories to avoid excessive RAM/disk usage."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT id, logs, history, occurrences_count FROM incidents")
                rows = cursor.fetchall()
                if not rows:
                    return
                
                needs_update = 0
                for row in rows:
                    hist_raw = row["history"] or "[]"
                    try:
                        hist_list = json.loads(hist_raw)
                        if isinstance(hist_list, list) and len(hist_list) > 15:
                            trimmed_hist = hist_list[-15:]
                            total_count = max(row["occurrences_count"] or 1, len(hist_list))
                            cursor.execute("""
                                UPDATE incidents 
                                SET history = ?, occurrences_count = ?
                                WHERE id = ?
                            """, (json.dumps(trimmed_hist, ensure_ascii=False), total_count, row["id"]))
                            needs_update += 1
                    except Exception:
                        pass
                        
                if needs_update > 0:
                    conn.commit()
                    logger.info(f"🧹 Historiales compactados (tope 15 registros FIFO) en {needs_update} incidencias para ahorrar disco y RAM.")
                    # Passive checkpoint to clean up WAL
                    cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception as e:
            logger.error(f"❌ Error durante la compactación de firmas: {e}")

    def _get_error_fingerprint(self, message: str) -> str:
        """Generates a normalized fingerprint for the error message, stripping dynamic variables."""
        sig = message.lower().strip()
        
        # 1. Strip standard ISO/Timestamp dates and times
        sig = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}[ tT]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[zZ]|[+-]\d{2}:?\d{2})?', '<date-time>', sig)
        sig = re.sub(r'\b\d{2}/[a-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s+[+-]\d{4})?\b', '<date-time>', sig)
        sig = re.sub(r'\b\d{2}[-/]\d{2}[-/]\d{4}\b', '<date>', sig)
        sig = re.sub(r'\b\d{4}[-/]\d{2}[-/]\d{2}\b', '<date>', sig)
        sig = re.sub(r'\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b', '<time>', sig)
        
        # 2. Strip UUIDs
        sig = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<uuid>', sig)
        
        # 3. Strip Hex addresses and dynamic hashes
        sig = re.sub(r'\b0x[0-9a-f]+\b', '<hex>', sig)
        sig = re.sub(r'\b[0-9a-f]{8,}\b', '<hash>', sig)
        
        # 4. Replace numbers
        sig = re.sub(r'\b\d+(?:\.\d+)?\b', '<num>', sig)
        
        # 5. Normalize whitespace
        sig = re.sub(r'\s+', ' ', sig).strip()
        
        if len(sig) > 150:
            return sig[:75] + "..." + sig[-75:]
        return sig

    def register_or_recur_incident(self, app: str, log_item: Dict[str, Any], matched_rules: List[Dict[str, Any]], ai_proposal: str) -> str:
        """Registers a new incident or processes a recurrence with bounded history (FIFO capped at 15 items)."""
        current_time = int(time.time())
        msg = log_item.get("message", "")
        fingerprint = self._get_error_fingerprint(msg)
        error_signature = f"{app}:{fingerprint}"
        
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT id, incident_num, status, history, occurrences_count
                    FROM incidents
                    WHERE error_signature = ?
                """, (error_signature,))
                row = cursor.fetchone()
                
                if row:
                    incident_id = row["id"]
                    incident_num = row["incident_num"]
                    old_status = row["status"]
                    old_history_str = row["history"]
                    current_count = (row["occurrences_count"] or 1) + log_item.get("count", 1)
                    
                    try:
                        history_list = json.loads(old_history_str)
                        if not isinstance(history_list, list):
                            history_list = []
                    except Exception:
                        history_list = []
                        
                    # Add current occurrence and cap at 15 items FIFO
                    history_list.append({
                        "timestamp": current_time,
                        "datetime": log_item.get("datetime", ""),
                        "message": msg[:300],  # Truncate to save disk
                        "count": log_item.get("count", 1)
                    })
                    history_list = history_list[-15:]
                    
                    has_ignore_rule = any(rule.get("action", "ALERT").upper() == "IGNORE" for rule in matched_rules)
                    new_status = "RESUELTA" if has_ignore_rule else "ABIERTA"
                    
                    kb_applied_json = None
                    if has_ignore_rule:
                        ignore_rule = next((r for r in matched_rules if r.get("action", "ALERT").upper() == "IGNORE"), None)
                        if ignore_rule:
                            kb_applied_json = json.dumps(ignore_rule, ensure_ascii=False)
                    
                    cursor.execute("""
                        UPDATE incidents
                        SET status = ?,
                            logs = ?,
                            matched_rules = ?,
                            ai_proposal = ?,
                            kb_applied = COALESCE(?, kb_applied),
                            updated_at = ?,
                            history = ?,
                            occurrences_count = ?
                        WHERE id = ?
                    """, (
                        new_status,
                        json.dumps({app: [log_item]}, ensure_ascii=False),
                        json.dumps(matched_rules, ensure_ascii=False),
                        ai_proposal,
                        kb_applied_json,
                        current_time,
                        json.dumps(history_list, ensure_ascii=False),
                        current_count,
                        incident_id
                    ))
                    conn.commit()
                    
                    if old_status in ("RESUELTA", "CERRADA"):
                        logger.info(f"🔄 [REAPERTURA] Incidente {incident_num} ({app}) reabierto por recurrencia del error.")
                    else:
                        logger.info(f"📈 [RECURRENCIA] Incidente {incident_num} ({app}) actualizado (#{current_count} ocurrencias).")
                    return incident_num
                else:
                    cursor.execute("SELECT COUNT(*) FROM incidents")
                    total_count = cursor.fetchone()[0]
                    incident_num = f"INC-{total_count + 1:04d}"
                    
                    has_ignore_rule = any(rule.get("action", "ALERT").upper() == "IGNORE" for rule in matched_rules)
                    initial_status = "RESUELTA" if has_ignore_rule else "ABIERTA"
                    
                    kb_applied_json = None
                    if has_ignore_rule:
                        ignore_rule = next((r for r in matched_rules if r.get("action", "ALERT").upper() == "IGNORE"), None)
                        if ignore_rule:
                            kb_applied_json = json.dumps(ignore_rule, ensure_ascii=False)
                    
                    initial_history = [{
                        "timestamp": current_time,
                        "datetime": log_item.get("datetime", ""),
                        "message": msg[:300],
                        "count": log_item.get("count", 1)
                    }]
                    
                    cursor.execute("""
                        INSERT INTO incidents (
                            incident_num, status, apps, error_signature, logs, matched_rules, ai_proposal, kb_applied, created_at, updated_at, history, occurrences_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        incident_num,
                        initial_status,
                        app,
                        error_signature,
                        json.dumps({app: [log_item]}, ensure_ascii=False),
                        json.dumps(matched_rules, ensure_ascii=False),
                        ai_proposal,
                        kb_applied_json,
                        current_time,
                        current_time,
                        json.dumps(initial_history, ensure_ascii=False),
                        log_item.get("count", 1)
                    ))
                    conn.commit()
                    
                    if has_ignore_rule:
                        logger.info(f"🔇 [AUTO-RESUELTO] Incidente {incident_num} para {app} auto-resuelto por regla de conocimiento.")
                    else:
                        logger.info(f"🚨 [NUEVO INCIDENTE] Registrado {incident_num} para {app}.")
                    return incident_num
        except Exception as e:
            logger.error(f"❌ Error al registrar/actualizar incidente en SQLite: {e}", exc_info=True)
            return ""

    def get_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves lightweight summaries of incidents for the main UI dashboard to save memory and bandwidth."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, incident_num, status, apps, error_signature, logs, matched_rules, ai_proposal, kb_applied, created_at, updated_at, occurrences_count
                    FROM incidents
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                incidents = []
                for row in rows:
                    incidents.append({
                        "id": row["id"],
                        "incident_num": row["incident_num"],
                        "status": row["status"],
                        "apps": row["apps"].split(",") if row["apps"] else [],
                        "error_signature": row["error_signature"],
                        "logs": json.loads(row["logs"]) if row["logs"] else {},
                        "matched_rules": json.loads(row["matched_rules"]) if row["matched_rules"] else [],
                        "ai_proposal": row["ai_proposal"],
                        "kb_applied": json.loads(row["kb_applied"]) if row["kb_applied"] else None,
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "occurrences_count": row["occurrences_count"] if "occurrences_count" in row.keys() else 1,
                        "history": [] # Loaded on demand via get_incident()
                    })
                return incidents
        except Exception as e:
            logger.error(f"❌ Error al obtener incidentes de la base de datos: {e}", exc_info=True)
            return []

    def get_incident(self, incident_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a specific incident including its full history for the detail modal."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, incident_num, status, apps, error_signature, logs, matched_rules, ai_proposal, kb_applied, created_at, updated_at, history, occurrences_count
                    FROM incidents
                    WHERE id = ?
                """, (incident_id,))
                row = cursor.fetchone()
                
                if row:
                    return {
                        "id": row["id"],
                        "incident_num": row["incident_num"],
                        "status": row["status"],
                        "apps": row["apps"].split(",") if row["apps"] else [],
                        "error_signature": row["error_signature"],
                        "logs": json.loads(row["logs"]) if row["logs"] else {},
                        "matched_rules": json.loads(row["matched_rules"]) if row["matched_rules"] else [],
                        "ai_proposal": row["ai_proposal"],
                        "kb_applied": json.loads(row["kb_applied"]) if row["kb_applied"] else None,
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "occurrences_count": row["occurrences_count"] if "occurrences_count" in row.keys() else 1,
                        "history": json.loads(row["history"]) if row["history"] else []
                    }
                return None
        except Exception as e:
            logger.error(f"❌ Error al obtener incidente {incident_id}: {e}", exc_info=True)
            return None

    def resolve_incident(self, incident_id: int, kb_rule: Dict[str, Any]) -> bool:
        """Resolves an incident by linking it to an applied Knowledge Base rule."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE incidents
                    SET status = 'RESUELTA',
                        kb_applied = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    json.dumps(kb_rule, ensure_ascii=False),
                    int(time.time()),
                    incident_id
                ))
                conn.commit()
                rows_affected = cursor.rowcount
            if rows_affected > 0:
                logger.info(f"🛡️ Incidente #{incident_id} marcado como RESUELTO aplicando regla: '{kb_rule.get('pattern')}'")
            return rows_affected > 0
        except Exception as e:
            logger.error(f"❌ Error al resolver incidente {incident_id}: {e}", exc_info=True)
            return False

    def auto_close_inactive_incidents(self, timeout_seconds: int = 7 * 24 * 3600) -> int:
        """Closes open incidents inactive for >1 week and purges closed incidents older than 30 days."""
        cutoff_time = int(time.time()) - timeout_seconds
        purge_time = int(time.time()) - (30 * 24 * 3600)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 1. Close inactive open incidents
                cursor.execute("""
                    UPDATE incidents
                    SET status = 'CERRADA',
                        updated_at = ?
                    WHERE status = 'ABIERTA' AND updated_at < ?
                """, (int(time.time()), cutoff_time))
                closed_count = cursor.rowcount
                
                # 2. Purge very old closed incidents (>30 days) to keep database compact
                cursor.execute("DELETE FROM incidents WHERE status = 'CERRADA' AND updated_at < ?", (purge_time,))
                purged_count = cursor.rowcount
                
                conn.commit()
                cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
                
            if closed_count > 0:
                logger.info(f"⏰ [Auto-Cierre] {closed_count} incidentes inactivos cerrados automáticamente.")
            if purged_count > 0:
                logger.info(f"🗑️ [Auto-Purga] {purged_count} incidentes antiguos (>30 días) eliminados de la base de datos.")
            return closed_count
        except Exception as e:
            logger.error(f"❌ Error en auto-cierre/purga de incidentes: {e}", exc_info=True)
            return 0

    def delete_incident(self, incident_id: int) -> bool:
        """Deletes a specific incident from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
                conn.commit()
                rows_affected = cursor.rowcount
            if rows_affected > 0:
                logger.info(f"🗑️ Incidente #{incident_id} eliminado.")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error al eliminar incidente #{incident_id}: {e}", exc_info=True)
            return False

    def delete_all_incidents(self) -> bool:
        """Deletes all incidents from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM incidents")
                conn.commit()
                rows_affected = cursor.rowcount
                cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
            logger.info(f"🗑️ Se han eliminado {rows_affected} incidentes del historial.")
            return True
        except Exception as e:
            logger.error(f"❌ Error al eliminar todos los incidentes: {e}", exc_info=True)
            return False

    # --- KNOWLEDGE BASE (kb_rules) SQLite CRUD ---
    
    def get_kb_rules(self) -> List[Dict[str, Any]]:
        """Retrieves all Knowledge Base rules from SQLite."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT id, pattern, description, cause, solution, commands, action, is_regex FROM kb_rules ORDER BY id DESC")
                rows = cursor.fetchall()
                
                rules = []
                for row in rows:
                    rules.append({
                        "id": row["id"],
                        "pattern": row["pattern"],
                        "description": row["description"] or "",
                        "cause": row["cause"] or "",
                        "solution": row["solution"],
                        "commands": row["commands"] or "",
                        "action": row["action"] if "action" in row.keys() else "ALERT",
                        "is_regex": bool(row["is_regex"]) if "is_regex" in row.keys() else False
                    })
                return rules
        except Exception as e:
            logger.error(f"❌ Error al obtener reglas de conocimiento: {e}", exc_info=True)
            return []

    def save_kb_rule(self, pattern: str, description: str, cause: str, solution: str, commands: str, action: str = "ALERT", original_pattern: Optional[str] = None, is_regex: bool = False) -> bool:
        """Saves (inserts or updates) a Knowledge Base rule in SQLite."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                search_pattern = original_pattern if original_pattern else pattern
                cursor.execute("SELECT id FROM kb_rules WHERE LOWER(pattern) = LOWER(?)", (search_pattern,))
                row = cursor.fetchone()
                
                if row:
                    rule_id = row[0]
                    cursor.execute("""
                        UPDATE kb_rules
                        SET pattern = ?,
                            description = ?,
                            cause = ?,
                            solution = ?,
                            commands = ?,
                            action = ?,
                            is_regex = ?
                        WHERE id = ?
                    """, (pattern, description, cause, solution, commands, action, int(is_regex), rule_id))
                else:
                    cursor.execute("""
                        INSERT INTO kb_rules (pattern, description, cause, solution, commands, action, is_regex)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (pattern, description, cause, solution, commands, action, int(is_regex)))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error al guardar regla de conocimiento: {e}", exc_info=True)
            return False

    def delete_kb_rule(self, pattern: str) -> bool:
        """Deletes a Knowledge Base rule by its pattern name."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM kb_rules WHERE LOWER(pattern) = LOWER(?)", (pattern,))
                conn.commit()
                rows_affected = cursor.rowcount
            return rows_affected > 0
        except Exception as e:
            logger.error(f"❌ Error al eliminar regla de conocimiento '{pattern}': {e}", exc_info=True)
            return False

    # --- SETTINGS SQLite CRUD ---

    def get_setting(self, key: str, default: str = "") -> str:
        """Retrieves a setting by key."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                return default
        except Exception as e:
            logger.error(f"❌ Error al obtener ajuste '{key}': {e}", exc_info=True)
            return default

    def set_setting(self, key: str, value: str) -> bool:
        """Saves a setting."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (key, value))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error al guardar ajuste '{key}': {e}", exc_info=True)
            return False
