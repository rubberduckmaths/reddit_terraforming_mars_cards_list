import os
import tomllib
import logging
from dataclasses import dataclass

# Enable DEBUG logging by default
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedditConfig:
    client_id: str
    client_secret: str
    username: str
    password: str
    user_agent: str


@dataclass(frozen=True)
class BotConfig:
    subreddit: str
    cards_csv: str
    reply_footer: str
    dry_run: bool
    state_file: str
    max_cards_per_reply: int


@dataclass(frozen=True)
class AppConfig:
    reddit: RedditConfig
    bot: BotConfig


def _redact(value: str, keep: int = 2) -> str:
    """
    Redact sensitive strings for logging.
    """
    if not value:
        return "<empty>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "..." + "*" * max(0, len(value) - keep - 3)


def load_config(path: str | None = None) -> AppConfig:
    """
    Load config from a TOML file (default: ./config.toml).
    """
    env_path = os.environ.get("TMARS_BOT_CONFIG")
    cfg_path = path or env_path or "config.toml"
    if path:
        logger.debug("Loading config from explicit path: %s", cfg_path)
    elif env_path:
        logger.debug("Loading config from TMARS_BOT_CONFIG env: %s", cfg_path)
    else:
        logger.debug("Loading config from default path: %s", cfg_path)

    try:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        logger.debug("TOML configuration parsed successfully")
    except FileNotFoundError:
        logger.exception("Configuration file not found at %s", cfg_path)
        raise
    except Exception:
        logger.exception("Failed to parse configuration file at %s", cfg_path)
        raise

    try:
        reddit_data = data["reddit"]
        bot_data = data["bot"]
    except KeyError:
        logger.exception("Missing required top-level sections in config (expected 'reddit' and 'bot')")
        raise

    try:
        reddit = RedditConfig(
            client_id=reddit_data["client_id"],
            client_secret=reddit_data["client_secret"],
            username=reddit_data["username"],
            password=reddit_data["password"],
            user_agent=reddit_data["user_agent"],
        )
    except KeyError:
        logger.exception("Missing one or more required 'reddit' fields in config")
        raise

    try:
        bot = BotConfig(
            subreddit=bot_data["subreddit"],
            cards_csv=bot_data["cards_csv"],
            reply_footer=bot_data.get("reply_footer", ""),
            dry_run=bool(bot_data.get("dry_run", False)),
            state_file=bot_data.get("state_file", "data/state.json"),
            max_cards_per_reply=int(bot_data.get("max_cards_per_reply", 8)),
        )
    except KeyError:
        logger.exception("Missing one or more required 'bot' fields in config")
        raise
    except ValueError:
        logger.exception("Invalid type for one of the 'bot' fields in config")
        raise

    # Safe summary for debugging (avoid logging secrets)
    logger.info(
        "Config loaded: subreddit=%s, cards_csv=%s, dry_run=%s, state_file=%s, max_cards_per_reply=%d, user_agent=%s, username=%s",
        bot.subreddit,
        bot.cards_csv,
        bot.dry_run,
        bot.state_file,
        bot.max_cards_per_reply,
        reddit.user_agent,
        _redact(reddit.username),
    )
    logger.debug(
        "Reddit credentials present: client_id=%s, client_secret=%s, password=%s",
        _redact(reddit.client_id),
        _redact(reddit.client_secret),
        _redact(reddit.password),
    )

    return AppConfig(reddit=reddit, bot=bot)
