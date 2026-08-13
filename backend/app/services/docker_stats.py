"""Container-Zustand über die Docker-Engine-API.

Zugriffsweg
-----------
Standardmäßig spricht das Backend **nicht** direkt mit ``/var/run/docker.sock``,
sondern mit dem Sidecar ``dockerproxy`` (tecnativa/docker-socket-proxy), der nur
lesende ``/containers``-, ``/info``- und ``/version``-Aufrufe durchlässt. Der
Docker-Socket ist gleichbedeutend mit Root auf dem Host — ihn in den von außen
erreichbaren Backend-Container zu hängen wäre eine unnötige Rechteausweitung.

``DOCKER_API_URL`` akzeptiert beides:

* ``http://dockerproxy:2375``          — Sidecar (Standard, empfohlen)
* ``unix:///var/run/docker.sock``      — direkter Socket (nur wenn bewusst gemountet)

Fällt die Quelle aus, liefert dieses Modul einen Report mit
``available=False`` und einer Begründung — die Systemübersicht zeigt dann alle
übrigen Kennzahlen weiter an, statt komplett zu scheitern.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
# Stats werden je Container einzeln abgefragt; begrenzt parallel, damit ein
# großer Stack die Engine nicht flutet.
_STATS_CONCURRENCY = 6


@dataclass
class ContainerInfo:
    name: str
    image: str
    state: str                     # running / exited / restarting / …
    status: str                    # "Up 3 hours (healthy)"
    health: str | None             # healthy / unhealthy / starting / None
    created_at: int | None
    started_at: str | None
    restart_count: int | None
    cpu_percent: float | None = None
    mem_bytes: int | None = None
    mem_limit_bytes: int | None = None
    mem_percent: float | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "image": self.image,
            "state": self.state,
            "status": self.status,
            "health": self.health,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "restart_count": self.restart_count,
            "cpu_percent": self.cpu_percent,
            "mem_bytes": self.mem_bytes,
            "mem_limit_bytes": self.mem_limit_bytes,
            "mem_percent": self.mem_percent,
        }


@dataclass
class DockerReport:
    available: bool
    reason: str | None = None
    engine_version: str | None = None
    containers: list[ContainerInfo] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.containers)

    @property
    def running(self) -> int:
        return sum(1 for c in self.containers if c.state == "running")

    @property
    def unhealthy(self) -> int:
        """Container, die Aufmerksamkeit brauchen: Healthcheck rot, oder ein
        Container, der laufen sollte, aber nicht läuft (exited/restarting).
        ``starting`` zählt bewusst nicht — das ist der Normalfall beim Hochlauf."""
        return sum(
            1
            for c in self.containers
            if c.health == "unhealthy" or c.state in ("exited", "dead", "restarting")
        )

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "engine_version": self.engine_version,
            "total": self.total,
            "running": self.running,
            "unhealthy": self.unhealthy,
            "containers": [c.as_dict() for c in self.containers],
        }


def _client() -> httpx.AsyncClient:
    """HTTP-Client für die Engine-API — je nach URL über TCP oder Unix-Socket."""
    url = settings.docker_api_url.strip()
    parsed = urlparse(url)
    if parsed.scheme in ("unix", "unix+http", "http+unix"):
        # unix:///var/run/docker.sock → Pfad steht im path-Teil (URL-dekodiert,
        # damit auch unix://%2Fvar%2Frun%2Fdocker.sock funktioniert).
        socket_path = unquote(parsed.path or parsed.netloc)
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=_TIMEOUT)
    return httpx.AsyncClient(base_url=url.rstrip("/"), timeout=_TIMEOUT)


def _health_of(container: dict[str, Any]) -> str | None:
    """Healthcheck-Zustand aus dem Listeneintrag ziehen.

    Die Listen-API liefert kein State-Objekt, aber das Status-Feld trägt den
    Zustand in Klammern: ``"Up 2 hours (healthy)"``.
    """
    status = container.get("Status") or ""
    for marker in ("(healthy)", "(unhealthy)", "(health: starting)"):
        if marker in status:
            return {"(healthy)": "healthy", "(unhealthy)": "unhealthy", "(health: starting)": "starting"}[marker]
    return None


def _parse_container(raw: dict[str, Any]) -> ContainerInfo:
    names = raw.get("Names") or []
    name = names[0].lstrip("/") if names else (raw.get("Id") or "")[:12]
    labels = raw.get("Labels") or {}
    # Bei Compose-Stacks ist der Servicename das, was Menschen erkennen
    # ("backend" statt "convoyplan-backend-1").
    service = labels.get("com.docker.compose.service")
    return ContainerInfo(
        name=service or name,
        image=raw.get("Image") or "",
        state=raw.get("State") or "unknown",
        status=raw.get("Status") or "",
        health=_health_of(raw),
        created_at=raw.get("Created"),
        started_at=None,
        restart_count=None,
    )


def _cpu_percent(stats: dict[str, Any]) -> float | None:
    """CPU-Auslastung aus einem Docker-Stats-Sample (gleiche Formel wie
    ``docker stats``: Delta der Container-Ticks gegen Delta der System-Ticks,
    skaliert auf die Zahl der verfügbaren Kerne)."""
    try:
        cpu = stats["cpu_stats"]
        pre = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        if cpu_delta <= 0 or system_delta <= 0:
            return None
        cores = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or []) or 1
        return round(cpu_delta / system_delta * cores * 100.0, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _mem_usage(stats: dict[str, Any]) -> tuple[int | None, int | None]:
    """(belegt, Limit) in Bytes. Der Page-Cache wird abgezogen, sonst zeigt der
    Wert vor allem Dateicache statt echtem Verbrauch (wie ``docker stats``)."""
    try:
        mem = stats["memory_stats"]
        usage = mem.get("usage")
        if usage is None:
            return None, mem.get("limit")
        detail = mem.get("stats") or {}
        cache = detail.get("inactive_file", detail.get("total_inactive_file", detail.get("cache", 0)))
        return max(0, usage - (cache or 0)), mem.get("limit")
    except (KeyError, TypeError):
        return None, None


async def _fetch_stats(client: httpx.AsyncClient, container_id: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(f"/containers/{container_id}/stats", params={"stream": "false"})
        if resp.is_success:
            return resp.json()
    except (httpx.HTTPError, ValueError):
        # Stats sind Beiwerk: Ein Container, der genau jetzt stoppt, oder ein
        # Timeout darf nicht den gesamten Container-Report kippen — der
        # Container erscheint dann eben ohne CPU-/RAM-Werte.
        logger.debug("Container-Stats für %s nicht abrufbar", container_id, exc_info=True)
    return None


async def collect(*, with_stats: bool | None = None) -> DockerReport:
    """Zustand aller Container einsammeln.

    ``with_stats`` steuert, ob zusätzlich CPU/RAM je Container abgefragt wird
    (ein Extra-Aufruf pro Container, jeweils ~1 s Sampling in der Engine).
    Ohne Angabe entscheidet ``DOCKER_STATS_ENABLED``.
    """
    if not settings.docker_metrics_enabled:
        return DockerReport(available=False, reason="Docker-Metriken deaktiviert (DOCKER_METRICS_ENABLED=false)")

    include_stats = settings.docker_stats_enabled if with_stats is None else with_stats

    try:
        async with _client() as client:
            resp = await client.get("/containers/json", params={"all": "true"})
            if resp.status_code == 403:
                return DockerReport(
                    available=False,
                    reason="Docker-API verweigert den Zugriff — im dockerproxy CONTAINERS=1 setzen.",
                )
            if not resp.is_success:
                return DockerReport(available=False, reason=f"Docker-API antwortete mit HTTP {resp.status_code}")

            raw_containers = resp.json()
            containers = [_parse_container(c) for c in raw_containers]

            engine_version: str | None = None
            try:
                version_resp = await client.get("/version")
                if version_resp.is_success:
                    engine_version = version_resp.json().get("Version")
            except (httpx.HTTPError, ValueError):
                pass  # Version ist Beiwerk — ihr Fehlen darf den Report nicht kippen

            if include_stats:
                running = [
                    (info, raw["Id"])
                    for info, raw in zip(containers, raw_containers)
                    if info.state == "running" and raw.get("Id")
                ]
                semaphore = asyncio.Semaphore(_STATS_CONCURRENCY)

                async def _enrich(info: ContainerInfo, cid: str) -> None:
                    async with semaphore:
                        stats = await _fetch_stats(client, cid)
                    if not stats:
                        return
                    info.cpu_percent = _cpu_percent(stats)
                    used, limit = _mem_usage(stats)
                    info.mem_bytes = used
                    info.mem_limit_bytes = limit
                    if used is not None and limit:
                        info.mem_percent = round(used / limit * 100.0, 2)

                await asyncio.gather(*(_enrich(i, c) for i, c in running))

            containers.sort(key=lambda c: c.name)
            return DockerReport(available=True, engine_version=engine_version, containers=containers)

    except (httpx.ConnectError, httpx.ConnectTimeout, FileNotFoundError, PermissionError) as exc:
        return DockerReport(
            available=False,
            reason=f"Docker-API nicht erreichbar unter {settings.docker_api_url} ({type(exc).__name__})",
        )
    except Exception as exc:  # pragma: no cover — Netz/Parser-Ausreißer
        logger.warning("Docker-Metriken fehlgeschlagen", exc_info=True)
        return DockerReport(available=False, reason=f"Docker-Metriken fehlgeschlagen: {exc}")
