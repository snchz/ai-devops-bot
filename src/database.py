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
        self.init_db()

    def init_db(self):
        """Initializes database schema if it does not exist, migrating if necessary."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if old table exists and needs recreation
                cursor.execute("PRAGMA table_info(incidents)")
                columns = [col[1] for col in cursor.fetchall()]
                
                # If table exists but doesn't have Phase 2 columns, drop it to migrate safely
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
                        history TEXT NOT NULL DEFAULT '[]'
                    )
                """)
                
                # Create knowledge base rules table (kb_rules)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS kb_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pattern TEXT UNIQUE NOT NULL,
                        description TEXT,
                        cause TEXT,
                        solution TEXT NOT NULL,
                        commands TEXT
                    )
                """)
                conn.commit()
            
            # Auto-migrate and consolidate old duplicate incidents on startup
            self._migrate_and_consolidate_signatures()
            
            logger.info(f"💾 Base de datos SQLite consolidada inicializada exitosamente en: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Error al inicializar la base de datos SQLite en '{self.db_path}': {e}", exc_info=True)

    def _migrate_and_consolidate_signatures(self):
        """
        Migrates existing database records to the new normalized signature format,
        consolidating/merging duplicates automatically.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Fetch all existing incidents
                cursor.execute("SELECT * FROM incidents")
                rows = cursor.fetchall()
                if not rows:
                    return
                
                logger.info(f"⚙️ Iniciando migración y consolidación de {len(rows)} incidencias históricas...")
                
                # Group by normalized signature: f"{app}:{fingerprint}"
                groups = {}
                for row in rows:
                    app = row["apps"]
                    # Parse logs to extract the original message to run through fingerprinting
                    try:
                        logs_dict = json.loads(row["logs"])
                        first_msg = ""
                        for app_name, items in logs_dict.items():
                            if items:
                                first_msg = items[0].get("message", "")
                                break
                    except Exception:
                        first_msg = ""
                        
                    if not first_msg:
                        # Fallback to the signature prefix if parsing fails
                        first_msg = row["error_signature"].split(":", 1)[-1]
                        
                    fingerprint = self._get_error_fingerprint(first_msg)
                    first_app = app.split(",")[0] if "," in app else app
                    norm_sig = f"{first_app}:{fingerprint}"
                    
                    if norm_sig not in groups:
                        groups[norm_sig] = []
                    groups[norm_sig].append(row)
                
                # Consolidate groups
                consolidated_count = 0
                for norm_sig, group in groups.items():
                    if len(group) == 1:
                        # Only one incident, just update its signature to the normalized one
                        row = group[0]
                        cursor.execute("""
                            UPDATE incidents
                            SET error_signature = ?
                            WHERE id = ?
                        """, (norm_sig, row["id"]))
                        continue
                    
                    # Duplicate found! We need to merge them.
                    group.sort(key=lambda r: r["id"]) # Sort by ID (oldest first)
                    primary = group[0]
                    duplicates = group[1:]
                    
                    primary_history = []
                    try:
                        primary_history = json.loads(primary["history"])
                    except Exception:
                        pass
                        
                    for dup in duplicates:
                        dup_logs = {}
                        try:
                            dup_logs = json.loads(dup["logs"])
                        except Exception:
                            pass
                            
                        # Add each log item in dup to the history list
                        for app_name, items in dup_logs.items():
                            for item in items:
                                primary_history.append({
                                    "timestamp": dup["created_at"],
                                    "datetime": item.get("datetime", ""),
                                    "message": item.get("message", ""),
                                    "count": item.get("count", 1)
                                })
                                
                        # Merge the duplicate's own history
                        try:
                            dup_hist = json.loads(dup["history"])
                            if isinstance(dup_hist, list):
                                primary_history.extend(dup_hist)
                        except Exception:
                            pass
                    
                    # Sort merged history by timestamp
                    primary_history.sort(key=lambda h: h.get("timestamp", 0))
                    
                    # Determine consolidated status: open if any is open
                    any_open = primary["status"] == "ABIERTA" or any(d["status"] == "ABIERTA" for d in duplicates)
                    cons_status = "ABIERTA" if any_open else "RESUELTA"
                    
                    cons_created = min(primary["created_at"], min(d["created_at"] for d in duplicates))
                    cons_updated = max(primary["updated_at"], max(d["updated_at"] for d in duplicates))
                    
                    cursor.execute("""
                        UPDATE incidents
                        SET error_signature = ?,
                            status = ?,
                            created_at = ?,
                            updated_at = ?,
                            history = ?
                        WHERE id = ?
                    """, (
                        norm_sig,
                        cons_status,
                        cons_created,
                        cons_updated,
                        json.dumps(primary_history, ensure_ascii=False),
                        primary["id"]
                    ))
                    
                    # Delete duplicates
                    dup_ids = [d["id"] for d in duplicates]
                    placeholders = ",".join("?" for _ in dup_ids)
                    cursor.execute(f"DELETE FROM incidents WHERE id IN ({placeholders})", tuple(dup_ids))
                    consolidated_count += len(duplicates)
                
                conn.commit()
                if consolidated_count > 0:
                    logger.info(f"✨ Migración de base de datos finalizada: se consolidaron y eliminaron {consolidated_count} incidencias duplicadas.")
                else:
                    logger.info("✅ Todos los incidentes históricos ya estaban normalizados y sin duplicados.")
        except Exception as e:
            logger.error(f"❌ Error durante la migración y consolidación de firmas: {e}", exc_info=True)


    def import_legacy_json_rules(self, json_path: str):
        """Imports rules from legacy JSON file into SQLite if the database is empty."""
        if not os.path.exists(json_path):
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if kb_rules is empty
                cursor.execute("SELECT COUNT(*) FROM kb_rules")
                count = cursor.fetchone()[0]
                if count > 0:
                    return # Already populated
                    
                # Read legacy JSON
                with open(json_path, "r", encoding="utf-8") as f:
                    rules = json.load(f)
                    
                if not rules:
                    return
                    
                logger.info(f"📦 Migrando {len(rules)} reglas heredadas desde {json_path} a SQLite...")
                for rule in rules:
                    cursor.execute("""
                        INSERT OR IGNORE INTO kb_rules (pattern, description, cause, solution, commands)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        rule.get("pattern", ""),
                        rule.get("description", ""),
                        rule.get("cause", ""),
                        rule.get("solution", ""),
                        rule.get("commands", "")
                    ))
                conn.commit()
            logger.info(f"🎉 Migración exitosa de reglas heredadas a la base de datos SQLite.")
        except Exception as e:
            logger.error(f"❌ Error al migrar reglas desde el archivo JSON heredado: {e}", exc_info=True)

    def _get_error_fingerprint(self, message: str) -> str:
        """Generates a normalized fingerprint for the error message, stripping dynamic variables (dates, timestamps, numbers, UUIDs, hex/hashes)."""
        sig = message.lower().strip()
        
        # 1. Strip standard ISO/Timestamp dates and times
        # Matches: YYYY-MM-DD HH:MM:SS, HH:MM:SS.mmm, etc.
        sig = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?', '<date>', sig)
        sig = re.sub(r'\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b', '<time>', sig)
        
        # 2. Strip UUIDs (matches 8-4-4-4-12 hex format)
        sig = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<uuid>', sig)
        
        # 3. Strip Hex addresses and dynamic hashes (length >= 8 hex characters)
        sig = re.sub(r'\b0x[0-9a-f]+\b', '<hex>', sig)
        sig = re.sub(r'\b[0-9a-f]{8,}\b', '<hash>', sig)
        
        # 4. Replace standalone numbers/integers/floats (to group connection ports, IDs, counts)
        sig = re.sub(r'\b\d+(?:\.\d+)?\b', '<num>', sig)
        
        # 5. Normalize whitespace and take first 150 chars
        sig = re.sub(r'\s+', ' ', sig)
        return sig[:150].strip()

    def register_or_recur_incident(self, app: str, log_item: Dict[str, Any], matched_rules: List[Dict[str, Any]], ai_proposal: str) -> str:
        """Registers a new incident or processes a recurrence/reopening of an existing one."""
        current_time = int(time.time())
        msg = log_item.get("message", "")
        fingerprint = self._get_error_fingerprint(msg)
        error_signature = f"{app}:{fingerprint}"
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Check if this error signature already exists
                cursor.execute("""
                    SELECT id, incident_num, status, logs, history, created_at, updated_at
                    FROM incidents
                    WHERE error_signature = ?
                """, (error_signature,))
                row = cursor.fetchone()
                
                if row:
                    # Recurrence!
                    incident_id = row["id"]
                    incident_num = row["incident_num"]
                    old_status = row["status"]
                    old_history_str = row["history"]
                    
                    try:
                        history_list = json.loads(old_history_str)
                    except Exception:
                        history_list = []
                        
                    # Add current occurrence to history
                    history_list.append({
                        "timestamp": current_time,
                        "datetime": log_item.get("datetime", ""),
                        "message": msg,
                        "count": log_item.get("count", 1)
                    })
                    
                    # Update fields. Reopen if it was resolved or closed
                    new_status = "ABIERTA"
                    
                    cursor.execute("""
                        UPDATE incidents
                        SET status = ?,
                            logs = ?,
                            matched_rules = ?,
                            ai_proposal = ?,
                            updated_at = ?,
                            history = ?
                        WHERE id = ?
                    """, (
                        new_status,
                        json.dumps({app: [log_item]}, ensure_ascii=False),
                        json.dumps(matched_rules, ensure_ascii=False),
                        ai_proposal,
                        current_time,
                        json.dumps(history_list, ensure_ascii=False),
                        incident_id
                    ))
                    conn.commit()
                    
                    if old_status in ("RESUELTA", "CERRADA"):
                        logger.info(f"🔄 [REAPERTURA] Incidente {incident_num} ({app}) reabierto por recurrencia del error.")
                    else:
                        logger.info(f"📈 [RECURRENCIA] Incidente {incident_num} ({app}) actualizado con nueva ocurrencia.")
                    return incident_num
                else:
                    # New incident!
                    cursor.execute("SELECT COUNT(*) FROM incidents")
                    total_count = cursor.fetchone()[0]
                    incident_num = f"INC-{total_count + 1:04d}"
                    
                    cursor.execute("""
                        INSERT INTO incidents (
                            incident_num, status, apps, error_signature, logs, matched_rules, ai_proposal, created_at, updated_at, history
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        incident_num,
                        "ABIERTA",
                        app,
                        error_signature,
                        json.dumps({app: [log_item]}, ensure_ascii=False),
                        json.dumps(matched_rules, ensure_ascii=False),
                        ai_proposal,
                        current_time,
                        current_time,
                        "[]"
                    ))
                    conn.commit()
                    logger.info(f"🚨 [NUEVO INCIDENTE] Registrado {incident_num} para {app}.")
                    return incident_num
        except Exception as e:
            logger.error(f"❌ Error al registrar/actualizar incidente en la base de datos: {e}", exc_info=True)
            return ""

    def get_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves history of incident cycles, ordered by newest first."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, incident_num, status, apps, error_signature, logs, matched_rules, ai_proposal, kb_applied, created_at, updated_at, history
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
                        "logs": json.loads(row["logs"]),
                        "matched_rules": json.loads(row["matched_rules"]),
                        "ai_proposal": row["ai_proposal"],
                        "kb_applied": json.loads(row["kb_applied"]) if row["kb_applied"] else None,
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "history": json.loads(row["history"]) if row["history"] else []
                    })
                return incidents
        except Exception as e:
            logger.error(f"❌ Error al obtener incidentes de la base de datos: {e}", exc_info=True)
            return []

    def resolve_incident(self, incident_id: int, kb_rule: Dict[str, Any]) -> bool:
        """Resolves an incident by linking it to an applied Knowledge Base rule."""
        try:
            with sqlite3.connect(self.db_path) as conn:
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
        """Closes open/resolved incidents that have not recurred for more than a week."""
        cutoff_time = int(time.time()) - timeout_seconds
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE incidents
                    SET status = 'CERRADA',
                        updated_at = ?
                    WHERE status = 'ABIERTA' AND updated_at < ?
                """, (int(time.time()), cutoff_time))
                conn.commit()
                rows_affected = cursor.rowcount
            if rows_affected > 0:
                logger.info(f"⏰ [Auto-Cierre] {rows_affected} incidentes inactivos cerrados automáticamente por inactividad de 1 semana.")
            return rows_affected
        except Exception as e:
            logger.error(f"❌ Error en el auto-cierre de incidentes: {e}", exc_info=True)
            return 0

    def delete_incident(self, incident_id: int) -> bool:
        """Deletes a specific incident from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
                conn.commit()
                rows_affected = cursor.rowcount
            if rows_affected > 0:
                logger.info(f"🗑️ Incidente #{incident_id} eliminado de la base de datos.")
                return True
            else:
                logger.warning(f"⚠️ Intento de eliminar incidente inexistente #{incident_id}.")
                return False
        except Exception as e:
            logger.error(f"❌ Error al eliminar incidente #{incident_id}: {e}", exc_info=True)
            return False

    # --- KNOWLEDGE BASE (kb_rules) SQLite CRUD ---
    
    def get_kb_rules(self) -> List[Dict[str, Any]]:
        """Retrieves all Knowledge Base rules from SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT id, pattern, description, cause, solution, commands FROM kb_rules ORDER BY id DESC")
                rows = cursor.fetchall()
                
                rules = []
                for row in rows:
                    rules.append({
                        "id": row["id"],
                        "pattern": row["pattern"],
                        "description": row["description"] or "",
                        "cause": row["cause"] or "",
                        "solution": row["solution"],
                        "commands": row["commands"] or ""
                    })
                return rules
        except Exception as e:
            logger.error(f"❌ Error al obtener reglas de conocimiento desde SQLite: {e}", exc_info=True)
            return []

    def save_kb_rule(self, pattern: str, description: str, cause: str, solution: str, commands: str, original_pattern: Optional[str] = None) -> bool:
        """Saves (inserts or updates) a Knowledge Base rule in SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                search_pattern = original_pattern if original_pattern else pattern
                
                # Check if it exists
                cursor.execute("SELECT id FROM kb_rules WHERE LOWER(pattern) = LOWER(?)", (search_pattern,))
                row = cursor.fetchone()
                
                if row:
                    # Update
                    rule_id = row[0]
                    cursor.execute("""
                        UPDATE kb_rules
                        SET pattern = ?,
                            description = ?,
                            cause = ?,
                            solution = ?,
                            commands = ?
                        WHERE id = ?
                    """, (pattern, description, cause, solution, commands, rule_id))
                else:
                    # Insert
                    cursor.execute("""
                        INSERT INTO kb_rules (pattern, description, cause, solution, commands)
                        VALUES (?, ?, ?, ?, ?)
                    """, (pattern, description, cause, solution, commands))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Error al guardar regla de conocimiento en SQLite: {e}", exc_info=True)
            return False

    def delete_kb_rule(self, pattern: str) -> bool:
        """Deletes a Knowledge Base rule by its pattern name."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM kb_rules WHERE LOWER(pattern) = LOWER(?)", (pattern,))
                conn.commit()
                rows_affected = cursor.rowcount
            return rows_affected > 0
        except Exception as e:
            logger.error(f"❌ Error al eliminar regla de conocimiento '{pattern}' de SQLite: {e}", exc_info=True)
            return False
