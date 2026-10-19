"""Teams response helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from castia import Message, Reaction
from castia.messaging.streaming import Streamer

logger = logging.getLogger(__name__)


class ActivityStatus:
    def __init__(
        self,
        msg: Message,
        *,
        status: str,
        min_visible_seconds: float = 0.0,
        refresh_seconds: float = 3.0,
        react: bool = True,
    ) -> None:
        self._msg = msg
        self._status = status
        self._min_visible_seconds = min_visible_seconds
        self._refresh_seconds = refresh_seconds
        self._react = react
        self._started_at = 0.0
        self._stream: Streamer | None = None
        self._refresh_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._started_at = time.monotonic()
        await asyncio.gather(self._msg.typing(), self._reaction(Reaction.eyes))
        self._stream = self._msg.stream(min_interval=0.75)
        await self._stream.update(self._status)
        self._refresh_task = asyncio.create_task(self._refresh())

    async def update(self, status: str) -> None:
        """Change the visible status mid-turn; the refresh loop keeps it alive."""
        if status == self._status:
            return
        self._status = status
        if self._stream is not None:
            with contextlib.suppress(Exception):
                await self._stream.update(status)

    async def finish(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        suggestions: dict[str, Any] | None = None,
    ) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task

        elapsed = time.monotonic() - self._started_at
        if elapsed < self._min_visible_seconds:
            await asyncio.sleep(self._min_visible_seconds - elapsed)

        if self._stream is None:
            await self._msg.say(text, attachments=attachments, suggestions=suggestions)
        else:
            await self._stream.finish(
                text=text, attachments=attachments, suggestions=suggestions
            )
        await self._reaction(Reaction.eyes, remove=True)
        await self._reaction(Reaction.check)

    async def cancel(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
        if self._stream is not None:
            with contextlib.suppress(Exception):
                await self._stream.finish(
                    text="Something went wrong handling that. Try `/health` for diagnostics."
                )
        await self._reaction(Reaction.eyes, remove=True)

    async def _reaction(self, reaction: str, *, remove: bool = False) -> None:
        """Best-effort status emoji on the user's message; never fails the turn."""
        if not self._react or not self._msg.id:
            return
        try:
            ok = await (
                self._msg.unreact(reaction) if remove else self._msg.react(reaction)
            )
        except Exception:
            logger.debug("Teams reaction %s failed", reaction, exc_info=True)
            return
        if not ok:
            logger.debug("Teams reaction %s was not accepted", reaction)

    async def _refresh(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_seconds)
            with contextlib.suppress(Exception):
                if self._stream is not None:
                    await self._stream.update(self._status)


async def start_activity_status(
    msg: Message,
    *,
    status: str = "Working...",
    min_visible_seconds: float = 0.0,
) -> ActivityStatus:
    working = ActivityStatus(
        msg,
        status=status,
        min_visible_seconds=min_visible_seconds,
    )
    await working.start()
    return working


async def send_streamed_reply(
    msg: Message,
    text: str,
    *,
    status: str = "Working...",
    attachments: list[dict[str, Any]] | None = None,
    suggestions: dict[str, Any] | None = None,
) -> None:
    working = await start_activity_status(msg, status=status)
    await working.finish(text, attachments=attachments, suggestions=suggestions)
