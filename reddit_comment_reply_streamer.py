import json
import re
import time
import logging
from pathlib import Path
from typing import Set, Iterable, Optional

import praw
from praw.exceptions import RedditAPIException, APIException  # APIException items live in RedditAPIException.items
from prawcore.exceptions import (
    PrawcoreException,
    Forbidden,
    NotFound,
    BadRequest,
    OAuthException,
    InsufficientScope,
    ServerError,
    RequestException,
    ResponseException,
)

from alias_extraction_and_card_resolution import resolve_cards_for_comment, format_card_reply
from reddit_bot_config_loader import AppConfig

# Enable DEBUG logging globally for the app
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


class StateStore:
    """
    Persist IDs of comments we already replied to (to avoid duplicates).
    """
    def __init__(self, path: str):
        self._path = Path(path)
        self._ids: Set[str] = set()
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._ids = set(map(str, data))
                logger.debug("Loaded %d processed comment IDs from %s", len(self._ids), self._path)
            except Exception as e:
                # start fresh on error
                logger.exception("Failed to load state from %s; starting fresh", self._path)
                self._ids = set()
        else:
            # ensure parent dir exists
            self._path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug("State file %s does not exist; created parent directory %s", self._path, self._path.parent)

    def save(self) -> None:
        try:
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(sorted(self._ids), f, indent=2)
            logger.debug("Saved %d processed comment IDs to %s", len(self._ids), self._path)
        except Exception:
            logger.exception("Failed to save state to %s", self._path)

    def has(self, comment_id: str) -> bool:
        self.load()
        return comment_id in self._ids

    def add(self, comment_id: str) -> None:
        self.load()
        self._ids.add(comment_id)
        self.save()


def make_reddit(cfg: AppConfig) -> praw.Reddit:
    # Note: Avoid passing unsupported kwargs to praw.Reddit to prevent TypeError.
    logger.debug("Creating Reddit client for subreddit=%s user_agent=%s", cfg.bot.subreddit, cfg.reddit.user_agent)
    return praw.Reddit(
        client_id=cfg.reddit.client_id,
        client_secret=cfg.reddit.client_secret,
        username=cfg.reddit.username,
        password=cfg.reddit.password,
        user_agent=cfg.reddit.user_agent,
    )


def _parse_rate_limit_delay(ex: RedditAPIException) -> int:
    """
    Extract ratelimit delay (in seconds) from a RedditAPIException if present.
    Returns a sensible default if not parseable.
    """
    delay_seconds = 60  # default backoff
    try:
        for item in getattr(ex, "items", []) or []:
            # item is praw.exceptions.APIException
            if isinstance(item, APIException) and str(item.error_type).upper() == "RATELIMIT":
                msg = item.message or ""
                m = re.search(r"(\d+)\s*(second|minute)", msg, flags=re.IGNORECASE)
                if m:
                    value = int(m.group(1))
                    unit = m.group(2).lower()
                    delay_seconds = value * (60 if unit.startswith("minute") else 1)
                logger.debug("Parsed ratelimit delay from message '%s': %d seconds", msg, delay_seconds)
                break
    except Exception:
        # Fallback to default delay
        logger.exception("Failed to parse ratelimit delay; using default %d seconds", delay_seconds)
    # Cap and pad a bit to be safe
    final_delay = min(delay_seconds + 5, 15 * 60)
    logger.debug("Using ratelimit delay: %d seconds", final_delay)
    return final_delay


def run_stream(
    reddit: praw.Reddit,
    cfg: AppConfig,
    lookup_fn,
) -> None:
    """
    Stream subreddit comments and reply when aliases are detected.
    """
    logger.info("Starting comment stream on r/%s (dry_run=%s)", cfg.bot.subreddit, cfg.bot.dry_run)
    subreddit = reddit.subreddit(cfg.bot.subreddit)
    me = None
    try:
        me = str(reddit.user.me())
        logger.debug("Authenticated as u/%s", me)
    except Exception:
        logger.exception("Unable to fetch authenticated user; proceeding without self-filter")
        me = None

    state = StateStore(cfg.bot.state_file)
    state.load()

    for comment in subreddit.stream.comments(skip_existing=True):
        try:
            author_str = str(getattr(comment, "author", "") or "")
            logger.debug("Processing comment id=%s by u/%s", comment.id, author_str or "<deleted>")

            # Skip our own comments or already processed comments
            if state.has(comment.id):
                logger.debug("Skipping already processed comment id=%s", comment.id)
                continue

            # Skip opt-out comments
            body_text = getattr(comment, "body", "") or ""
            if "optout" in (body_text.lower()):
                logger.debug("Skipping comment id=%s due to opt-out", comment.id)
                state.add(comment.id)
                continue

            cards = resolve_cards_for_comment(body_text, lookup_fn)
            if not cards:
                logger.debug("No cards resolved for comment id=%s", comment.id)
                state.add(comment.id)
                continue

            if len(cards) > cfg.bot.max_cards_per_reply:
                logger.debug("Truncating cards from %d to %d for comment id=%s",
                             len(cards), cfg.bot.max_cards_per_reply, comment.id)
                cards = cards[: cfg.bot.max_cards_per_reply]

            reply_text = format_card_reply(cards, footer=cfg.bot.reply_footer)

            if cfg.bot.dry_run:
                logger.info("[DRY RUN] Would reply to comment id=%s by u/%s with %d cards",
                            comment.id, author_str or "<deleted>", len(cards))
                print(f"[DRY RUN] Would reply to comment {comment.id} by u/{comment.author}:\n{reply_text}\n")
                state.add(comment.id)
                continue

            # Try to reply with robust exception handling
            try:
                logger.info("Replying to comment id=%s by u/%s with %d cards", comment.id, author_str or "<deleted>", len(cards))
                comment.reply(reply_text)
                logger.debug("Successfully replied to comment id=%s", comment.id)
            except RedditAPIException as e:
                logger.warning("RedditAPIException on reply to comment id=%s; attempting backoff and retry", comment.id, exc_info=True)
                delay = _parse_rate_limit_delay(e)
                time.sleep(delay)
                try:
                    comment.reply(reply_text)
                    logger.debug("Successfully replied to comment id=%s after retry", comment.id)
                except (RedditAPIException, Forbidden, NotFound, BadRequest, OAuthException, InsufficientScope):
                    logger.exception("Giving up on comment id=%s after retry due to non-retriable/duplicate API error", comment.id)
            except (Forbidden, NotFound, BadRequest, OAuthException, InsufficientScope):
                logger.exception("Permission/auth/resource error; cannot reply to comment id=%s", comment.id)
            except (ServerError, RequestException, ResponseException, PrawcoreException):
                logger.exception("Transient backend/network error; skipping comment id=%s and continuing", comment.id)
                time.sleep(5)

            # Mark as processed regardless to avoid repeated attempts on problematic comments
            state.add(comment.id)

        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt; stopping stream.")
            break
        except Exception:
            logger.exception("Unexpected error while processing a comment; sleeping briefly and continuing")
            time.sleep(2)
            continue
