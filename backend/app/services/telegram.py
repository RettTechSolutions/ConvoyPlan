"""Die Bot-API von Telegram, so schmal wie nötig.

Nur ausgehend und nur Long Polling (``getUpdates``): Viele Instanzen stehen
hinter NAT, ein Webhook bräuchte eine eingehende Route ins Backend. Was mit den
Updates geschieht, entscheidet ``services/aktionsseite_telegram.py``; hier steht
nur der Draht.

Das Token steht in der Adresse jedes Aufrufs (``/bot<token>/<methode>``). Es
darf deshalb in keiner Fehlermeldung landen — ``TelegramFehler`` trägt nur die
Beschreibung von Telegram, nie die URL, und httpx-Ausnahmen werden ohne ihre
Anfrage weitergereicht.
"""
from dataclasses import dataclass

import httpx

from app.config import settings

# Länger als das Long Polling selbst (``POLL_SEKUNDEN``), sonst bricht der
# Client jede ruhige Minute als Fehler ab.
TIMEOUT = httpx.Timeout(10.0, read=40.0)
POLL_SEKUNDEN = 25
# Größer liefert ``getFile`` nicht aus.
DATEI_MAX_BYTES = 20 * 1024 * 1024


class TelegramFehler(Exception):
    """Telegram hat abgelehnt oder war nicht erreichbar.

    ``code`` ist der HTTP-/API-Fehlercode (0 bei Netzfehlern), ``warten`` die
    Sekunden aus ``retry_after`` bei 429."""

    def __init__(self, code: int, beschreibung: str, warten: int | None = None):
        super().__init__(f"Telegram {code}: {beschreibung}")
        self.code = code
        self.beschreibung = beschreibung
        self.warten = warten


@dataclass(frozen=True)
class BotInfo:
    id: int
    username: str
    # Ohne das sieht der Bot in Gruppen nur Befehle und Antworten an ihn —
    # keine Fotos. Abschalten bei BotFather: /setprivacy → Disable.
    liest_alles: bool


class TelegramApi:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._token = token
        self._basis = settings.telegram_api_url.rstrip("/")
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport)

    async def aufruf(self, methode: str, **params) -> dict | list | bool:
        daten = {k: v for k, v in params.items() if v is not None}
        try:
            async with self._client() as c:
                r = await c.post(f"{self._basis}/bot{self._token}/{methode}", json=daten)
        except httpx.HTTPError as e:
            # Nur der Typ: ``str(e)`` kann die Adresse samt Token enthalten.
            raise TelegramFehler(0, type(e).__name__) from None
        try:
            antwort = r.json()
        except ValueError:
            raise TelegramFehler(r.status_code, "keine JSON-Antwort") from None
        if not antwort.get("ok"):
            warten = (antwort.get("parameters") or {}).get("retry_after")
            raise TelegramFehler(
                antwort.get("error_code") or r.status_code,
                str(antwort.get("description") or "unbekannter Fehler")[:300],
                warten,
            )
        return antwort.get("result")

    async def ich(self) -> BotInfo:
        r = await self.aufruf("getMe")
        return BotInfo(
            id=r["id"],
            username=r.get("username") or "",
            liest_alles=bool(r.get("can_read_all_group_messages")),
        )

    async def befehle_setzen(self, befehle: list[tuple[str, str]], bereich: str) -> None:
        """Die Befehlsliste, die Telegram beim Tippen von „/“ zeigt — je
        ``bereich`` (``all_private_chats``, ``all_group_chats``) eine eigene."""
        await self.aufruf(
            "setMyCommands",
            commands=[{"command": c, "description": d} for c, d in befehle],
            scope={"type": bereich},
        )

    async def updates(self, offset: int, warten: int = POLL_SEKUNDEN) -> list[dict]:
        return await self.aufruf(
            "getUpdates",
            offset=offset,
            timeout=warten,
            allowed_updates=["message", "edited_message", "callback_query"],
        )

    async def senden(
        self,
        chat_id: int,
        text: str,
        *,
        thread_id: int | None = None,
        antwort_auf: int | None = None,
        knoepfe: list[list[dict]] | None = None,
        erzwinge_antwort: bool = False,
    ) -> dict:
        markup = None
        if knoepfe is not None:
            markup = {"inline_keyboard": knoepfe}
        elif erzwinge_antwort:
            # ``selective``: nur für den, auf dessen Nachricht geantwortet wird.
            markup = {"force_reply": True, "selective": True}
        return await self.aufruf(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            reply_parameters={"message_id": antwort_auf, "allow_sending_without_reply": True}
            if antwort_auf
            else None,
            reply_markup=markup,
            link_preview_options={"is_disabled": True},
        )

    async def bearbeiten(
        self, chat_id: int, message_id: int, text: str, knoepfe: list[list[dict]] | None
    ) -> None:
        try:
            await self.aufruf(
                "editMessageText",
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup={"inline_keyboard": knoepfe or []},
                link_preview_options={"is_disabled": True},
            )
        except TelegramFehler as e:
            # Unverändert ist kein Fehler: Zwei Updates hintereinander können
            # dieselbe Karte ergeben.
            if "message is not modified" not in e.beschreibung:
                raise

    async def quittieren(self, callback_id: str, text: str | None = None, alarm: bool = False) -> None:
        await self.aufruf(
            "answerCallbackQuery", callback_query_id=callback_id, text=text, show_alert=alarm
        )

    async def datei(self, file_id: str) -> bytes:
        info = await self.aufruf("getFile", file_id=file_id)
        if (info.get("file_size") or 0) > DATEI_MAX_BYTES:
            raise TelegramFehler(413, "Datei zu groß")
        pfad = info.get("file_path")
        if not pfad:
            raise TelegramFehler(404, "Datei nicht abrufbar")
        try:
            async with self._client() as c:
                r = await c.get(f"{self._basis}/file/bot{self._token}/{pfad}")
        except httpx.HTTPError as e:
            raise TelegramFehler(0, type(e).__name__) from None
        if r.status_code != 200:
            raise TelegramFehler(r.status_code, "Datei nicht abrufbar")
        if len(r.content) > DATEI_MAX_BYTES:
            raise TelegramFehler(413, "Datei zu groß")
        return r.content
