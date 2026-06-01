import sqlite3
import json
import time
from typing import List, Dict, Any, Optional
from src.logger import logger

class Database:
    """Manages local SQLite database for incident and logs history persistence."""
    
    def __init__(self, db_path: str = "history.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initializes database schema if it does not exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp INTEGER NOT NULL,
                        apps TEXT NOT NULL,
                        logs TEXT NOT NULL,
                        matched_rules TEXT NOT NULL,
                        ai_proposal TEXT NOT NULL
                    )
                """)
                conn.commit()
            logger.info(f"💾 Base de datos SQLite inicializada exitosamente en: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Error al inicializar la base de datos SQLite en '{self.db_path}': {e}", exc_info=True)

    def save_incident(self, apps: List[str], logs: Dict[str, Any], matched_rules: List[Dict[str, Any]], ai_proposal: str) -> Optional[int]:
        """Saves a new incident cycle into the database."""
        if not apps:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO incidents (timestamp, apps, logs, matched_rules, ai_proposal)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    int(time.time()),
                    ",".join(apps),
                    json.dumps(logs, ensure_ascii=False),
                    json.dumps(matched_rules, ensure_ascii=False),
                    ai_proposal
                ))
                conn.commit()
                inserted_id = cursor.lastrowid
            logger.info(f"📝 Incidente #{inserted_id} guardado en base de datos para las aplicaciones: {apps}")
            return inserted_id
        except Exception as e:
            logger.error(f"❌ Error al guardar incidente en la base de datos: {e}", exc_info=True)
            return None

    def get_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves history of incident cycles, ordered by newest first."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, timestamp, apps, logs, matched_rules, ai_proposal
                    FROM incidents
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                incidents = []
                for row in rows:
                    incidents.append({
                        "id": row["id"],
                        "timestamp": row["timestamp"],
                        "apps": row["apps"].split(",") if row["apps"] else [],
                        "logs": json.loads(row["logs"]),
                        "matched_rules": json.loads(row["matched_rules"]),
                        "ai_proposal": row["ai_proposal"]
                    })
                return incidents
        except Exception as e:
            logger.error(f"❌ Error al obtener incidentes de la base de datos: {e}", exc_info=True)
            return []

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
