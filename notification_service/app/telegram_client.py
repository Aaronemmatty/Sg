from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("notification_service.telegram")


class TelegramClient:
    """
    Outbound-only Telegram notification client.

    Guarantees:
      - Strictly SEND-ONLY: No polling (`getUpdates`), no incoming webhooks, no interactive commands.
      - Non-blocking: Sends occur asynchronously with bounded timeouts.
      - Resilient: Automatic retry with exponential backoff; failures log warnings and discard gracefully.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
        backoff_base_s: Optional[float] = None,
    ) -> None:
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.timeout = timeout_seconds or settings.TELEGRAM_TIMEOUT_SECONDS
        self.max_retries = max_retries or settings.TELEGRAM_MAX_RETRIES
        self.backoff_base = backoff_base_s or settings.TELEGRAM_RETRY_BACKOFF_BASE_SECONDS
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Sends a notification message to the configured Telegram chat.
        Returns True if delivered, False if failed after all retries.
        Never raises uncaught exceptions to the caller.
        """
        if not self.bot_token or not self.chat_id:
            logger.warning(
                "telegram_notification_skipped",
                extra={"reason": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured"},
            )
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        client = await self.get_client()

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post(url, json=payload)

                if response.status_code == 200:
                    logger.info("telegram_message_delivered", extra={"attempt": attempt})
                    return True

                if response.status_code == 429:
                    # Telegram rate limit: parse retry_after if available
                    retry_after = self.backoff_base * (2 ** (attempt - 1))
                    try:
                        retry_after = float(response.json().get("parameters", {}).get("retry_after", retry_after))
                    except Exception:
                        pass
                    logger.warning(
                        "telegram_rate_limited",
                        extra={"status_code": 429, "attempt": attempt, "retry_after": retry_after},
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # 4xx (e.g. 400 Bad Request, 401 Unauthorized) are client errors - don't retry endlessly
                if 400 <= response.status_code < 500:
                    logger.error(
                        "telegram_client_error",
                        extra={"status_code": response.status_code, "response": response.text[:300]},
                    )
                    return False

                # 5xx Server errors - retry with backoff
                logger.warning(
                    "telegram_server_error",
                    extra={"status_code": response.status_code, "attempt": attempt},
                )

            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
                logger.warning(
                    "telegram_network_error",
                    extra={"attempt": attempt, "error": str(exc)},
                )
            except Exception as exc:
                logger.error(
                    "telegram_unexpected_error",
                    extra={"attempt": attempt, "error": str(exc)},
                )

            if attempt < self.max_retries:
                delay = self.backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        logger.error("telegram_notification_failed_all_retries", extra={"max_retries": self.max_retries})
        return False
