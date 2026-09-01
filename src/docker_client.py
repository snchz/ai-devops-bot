import os
import re
import struct
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Final, Set
import httpx
from src.config import Config
from src.logger import logger

DOCKER_UDS_BASE_URL: Final[str] = os.getenv("DOCKER_UDS_BASE_URL", "http://docker")
ERROR_SIGNATURES: Final[str] = r'(?i)(error|fatal|panic|exception|traceback|critical|emerg|failed|fail\b|refused|timeout|crash)'


class DockerClient:
    """Client to query Docker Engine API directly via Unix Domain Socket or HTTP proxy."""

    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.socket_path: str = config.docker_socket
        self.docker_url: Optional[str] = config.docker_url
        self.ignored_containers: Set[str] = set(config.ignored_containers)

        if self.docker_url:
            self.client: httpx.AsyncClient = httpx.AsyncClient(base_url=self.docker_url, timeout=20)
        else:
            transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
            self.client = httpx.AsyncClient(transport=transport, base_url=DOCKER_UDS_BASE_URL, timeout=20)

        self.error_pattern: re.Pattern = re.compile(ERROR_SIGNATURES, re.IGNORECASE)

    def _parse_multiplexed_stream(self, raw_bytes: bytes) -> List[str]:
        """Parses Docker's 8-byte multiplexed stdout/stderr stream frames into text lines."""
        lines: List[str] = []
        n: int = len(raw_bytes)
        i: int = 0

        is_multiplexed: bool = (n >= 8 and raw_bytes[0] in (1, 2) and raw_bytes[1:4] == b'\x00\x00\x00')

        if not is_multiplexed:
            text = raw_bytes.decode('utf-8', errors='replace')
            return [line.strip() for line in text.splitlines() if line.strip()]

        while i + 8 <= n:
            frame_size = struct.unpack('>I', raw_bytes[i + 4:i + 8])[0]
            i += 8
            if i + frame_size > n:
                frame_data = raw_bytes[i:]
                i = n
            else:
                frame_data = raw_bytes[i:i + frame_size]
                i += frame_size

            text = frame_data.decode('utf-8', errors='replace')
            for line in text.splitlines():
                cleaned = line.strip()
                if cleaned:
                    lines.append(cleaned)
        return lines

    def _parse_log_line(self, raw_line: str) -> Tuple[int, str, str]:
        """
        Parses a Docker log line that starts with an RFC3339 timestamp.
        Returns: (timestamp_ns, formatted_datetime_utc, clean_message)
        """
        line: str = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_line).strip()
        match: Optional[re.Match] = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\s+(.*)$', line)
        if match:
            ts_str, msg = match.group(1), match.group(2).strip()
            parsed = self._try_parse_rfc3339(ts_str, msg)
            if parsed:
                return parsed

        now_ns: int = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        dt_str: str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return now_ns, dt_str, line

    @staticmethod
    def _try_parse_rfc3339(ts_str: str, msg: str) -> Optional[Tuple[int, str, str]]:
        try:
            clean_ts = ts_str.rstrip('Z')
            if '.' in clean_ts:
                date_part, nano_part = clean_ts.split('.', 1)
                nano_part = (nano_part + '000000000')[:9]
                dt = datetime.fromisoformat(f"{date_part}.{nano_part[:6]}")
                ts_ns = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000) + int(nano_part[6:])
            else:
                dt = datetime.fromisoformat(clean_ts)
                ts_ns = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)
            dt_utc_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            return ts_ns, dt_utc_str, msg
        except (ValueError, TypeError):
            return None

    async def get_running_containers(self) -> List[str]:
        """Returns the list of active container names."""
        try:
            resp = await self.client.get("/containers/json")
            if resp.status_code != 200:
                logger.error(f"Error consultando contenedores en Docker API ({resp.status_code}): {resp.text}")
                return []
            data = resp.json()
            names: List[str] = []
            for c in data:
                raw_names = c.get("Names", [])
                if raw_names:
                    name = raw_names[0].lstrip("/")
                    if name not in self.ignored_containers:
                        names.append(name)
            return names
        except httpx.RequestError as err:
            logger.error(f"Error de conexión con Docker Socket: {err}")
            return []

    async def fetch_logs(self, start_ns: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """Fetches and parses new error logs across all running Docker containers."""
        containers: List[str] = await self.get_running_containers()
        if not containers:
            return []

        all_logs: List[Dict[str, Any]] = []
        since_sec: int = int(start_ns / 1_000_000_000) if start_ns else int(datetime.now(timezone.utc).timestamp() - 300)

        for container_name in containers:
            container_logs = await self._fetch_container_logs(container_name, since_sec, start_ns)
            all_logs.extend(container_logs)

        all_logs.sort(key=lambda x: x.get("timestamp_ns", 0))
        return all_logs

    async def _fetch_container_logs(
        self,
        container_name: str,
        since_sec: int,
        start_ns: Optional[int]
    ) -> List[Dict[str, Any]]:
        logs: List[Dict[str, Any]] = []
        try:
            params = {
                "stdout": "true",
                "stderr": "true",
                "since": str(since_sec),
                "timestamps": "true",
                "tail": "100"
            }
            resp = await self.client.get(f"/containers/{container_name}/logs", params=params)
            if resp.status_code != 200:
                return logs

            lines = self._parse_multiplexed_stream(resp.content)
            for line in lines:
                ts_ns, dt_str, msg = self._parse_log_line(line)
                if start_ns and ts_ns <= start_ns:
                    continue
                if not self.error_pattern.search(msg):
                    continue

                logs.append({
                    "timestamp_ns": ts_ns,
                    "labels": {"container_name": container_name},
                    "message": msg,
                    "datetime": dt_str
                })
        except httpx.RequestError as err:
            logger.debug(f"No se pudieron leer logs de {container_name}: {err}")
        return logs

    async def fetch_context_logs(
        self,
        app_name: str,
        target_ts_ns: int,
        window_minutes: int = 5
    ) -> List[Dict[str, Any]]:
        """Fetches full unfiltered context logs around a specific timestamp for debugging."""
        half_window_sec: int = int(window_minutes * 60 / 2)
        target_sec: int = int(target_ts_ns / 1_000_000_000)
        since_sec: int = max(0, target_sec - half_window_sec)
        until_sec: int = target_sec + half_window_sec

        try:
            params = {
                "stdout": "true",
                "stderr": "true",
                "since": str(since_sec),
                "until": str(until_sec),
                "timestamps": "true",
                "tail": "500"
            }
            resp = await self.client.get(f"/containers/{app_name}/logs", params=params)
            if resp.status_code != 200:
                return []

            lines = self._parse_multiplexed_stream(resp.content)
            context_logs: List[Dict[str, Any]] = []
            for line in lines:
                ts_ns, dt_str, msg = self._parse_log_line(line)
                context_logs.append({
                    "timestamp_ns": ts_ns,
                    "labels": {"container_name": app_name},
                    "message": msg,
                    "datetime": dt_str
                })
            context_logs.sort(key=lambda x: x.get("timestamp_ns", 0))
            return context_logs
        except httpx.RequestError as err:
            logger.error(f"Error consultando logs de contexto para {app_name}: {err}")
            return []

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        try:
            await self.client.aclose()
        except httpx.HTTPError as err:
            logger.debug(f"Error closing Docker HTTP client: {err}")
