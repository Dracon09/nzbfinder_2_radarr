#!/usr/bin/env python3
import os
import sys
import time
import signal
import threading
import re
import logging
import requests
import yaml
import xml.etree.ElementTree as ET
import keyboard  # ✅ Detects keypress for manual execution
from dotenv import load_dotenv
from arrapi import RadarrAPI
from pydantic import BaseModel
from typing import List, Optional, Tuple, cast
import datetime

# -----------------------------------------------------------------------------
# Fail Fast if config files missing
# -----------------------------------------------------------------------------

# Define the config folder and file paths.
CONFIG_FOLDER = "config"
ENV_FILE_PATH = os.path.join(CONFIG_FOLDER, ".env")
CONFIG_FILE_PATH = os.path.join(CONFIG_FOLDER, "config.yaml")

# Ensure the config folder itself exists.
if not os.path.exists(CONFIG_FOLDER):
    logging.error(f"Missing configuration folder: {CONFIG_FOLDER}. Please create it and add your configuration files.")
    sys.exit(1)

# Fail fast if the .env file is missing.
if not os.path.exists(ENV_FILE_PATH):
    logging.error(f"Missing essential file: {ENV_FILE_PATH}. Please create it with the required environment variables.")
    sys.exit(1)

# Fail fast if the config.yaml file is missing.
if not os.path.exists(CONFIG_FILE_PATH):
    logging.error(f"Missing essential file: {CONFIG_FILE_PATH}. Please create it with your configuration settings.")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Load environment variables
# -----------------------------------------------------------------------------

# Now that we've ensured the necessary files exist, load them.
load_dotenv(ENV_FILE_PATH)
NZBFINDER_API_KEY = os.getenv("NZBFINDER_API_KEY")
RADARR_URL = os.getenv("RADARR_URL")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

class ConfigModel(BaseModel):
    execution_interval: int = 15  # in minutes
    max_stored_guids: int = 1000
    debug_mode: bool = False
    debug_logging: bool = False
    use_keyboard: bool = True
    movie_folder: str = "/data/media/movies"
    quality_profile: str = "RARBG1080p265Pyhton"
    match_patterns: Optional[List[str]] = []
    not_match_patterns: Optional[List[str]] = []

    @classmethod
    def load_from_file(cls, filename: str) -> "ConfigModel":
        try:
            with open(filename, "r", encoding="utf-8") as file:
                raw_config = yaml.safe_load(file)
            return cls(**raw_config)
        except Exception as error1:
            logging.error(f"❌ Failed to load or validate config file: {error1}")
            sys.exit(1)


# Temporary basic logging for config loading errors.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
CONFIG_FILE = "config/config.yaml"
config_model = ConfigModel.load_from_file(CONFIG_FILE)

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------

# Ensure the config folder exists, so we can store script.log there
config_folder = "config"
if not os.path.exists(config_folder):
    os.makedirs(config_folder)

DEBUG_LOGGING = config_model.debug_logging
LOG_FILE = os.path.join(config_folder, "script.log")
GUID_TRACK_FILE = os.path.join(config_folder, "scanned_guids.txt")
INVALID_MOVIE_LOG_FILE = os.path.join(config_folder, "invalid_movie.log")

# Remove any existing handlers.
for handler in logging.getLogger().handlers:
    logging.getLogger().removeHandler(handler)

logging.basicConfig(
    level=logging.DEBUG if DEBUG_LOGGING else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Banner and initial log messages
logging.info("*******************************************************************************************")
logging.info("  _   _ __________  ______             _           ")
logging.info(" | \\ | |___  /  _ \\|  ___|(_)         | |          ")
logging.info(" |  \\| |  / /| |_) | |__   _ _ __   __| | ___ _ __ ")
logging.info(" | . ` | / / |  _ <|  __| | | '_ \\ / _` |/ _ \\ '__|")
logging.info(" | |\\  |/ /__| |_) | |    | | | | | (_| |  __/ |   ")
logging.info(" |_| \\_/_____|____/|_|    |_|_| |_|\\__,_|\\___|_|   ")
logging.info("*******************************************************************************************")
logging.info("🚀 Loaded configuration from config.yaml")

# Extract settings
EXECUTION_INTERVAL = config_model.execution_interval
MAX_STORED_GUIDS = config_model.max_stored_guids
DEBUG_MODE = config_model.debug_mode
USE_KEYBOARD = config_model.use_keyboard
MOVIE_FOLDER = config_model.movie_folder
QUALITY_PROFILE = config_model.quality_profile
RSS_FEED_URL = f"https://nzbfinder.ws/rss/category?id=2040&dl=1&num=50&api_token={NZBFINDER_API_KEY}"
GUID_TRACK_FILE = os.path.join("config", "scanned_guids.txt")

# -----------------------------------------------------------------------------
# Radarr API connection
# -----------------------------------------------------------------------------

try:
    radarr = RadarrAPI(RADARR_URL, RADARR_API_KEY)
    logging.info("✅ Connected to Radarr successfully!")
except Exception as error:
    logging.error(f"❌ Failed to connect to Radarr: {error}")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Global Flags, Signal Handling, and Cumulative Totals
# -----------------------------------------------------------------------------

running = True
manual_run_event = threading.Event()  # Used to signal a manual run

# Cumulative counters for all executions since the script started
total_movies_added = 0
total_movies_exists = 0
total_movies_invalid = 0
total_movies_excluded = 0

imdb_ids_to_add = []  # now storing tuples of (imdb_id, title)


def signal_handler(_sig, _frame):
    logging.info("Received termination signal. Shutting down gracefully...")
    global running
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def load_regex_patterns(config: ConfigModel) -> Tuple[Optional[re.Pattern], Optional[re.Pattern]]:
    try:
        match_patterns_list = config.match_patterns or []
        not_match_patterns_list = config.not_match_patterns or []
        match_patterns = "|".join(match_patterns_list)
        not_match_patterns = "|".join(not_match_patterns_list)
        logging.info("*******************************************************************************************")
        logging.info(
            f"🚀 Loaded {len(match_patterns_list)} match patterns and {len(not_match_patterns_list)} exclusion patterns."
        )
        match_regex = re.compile(match_patterns, re.IGNORECASE) if match_patterns else None
        not_match_regex = re.compile(not_match_patterns, re.IGNORECASE) if not_match_patterns else None
        return match_regex, not_match_regex
    except Exception as error2:
        logging.error(f"❌ Failed to compile regex patterns: {error2}")
        sys.exit(1)


def filter_title(title: str, match_regex: Optional[re.Pattern], not_match_regex: Optional[re.Pattern]) -> bool:
    if not title:
        return False
    if match_regex and not match_regex.search(title):
        return False
    if not_match_regex and not_match_regex.search(title):
        return False
    return True


def fetch_rss_feed(url: str, max_attempts: int = 5, initial_delay: int = 5) -> requests.Response:
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response
        except Exception as error3:
            logging.error(f"Attempt {attempt}: Error fetching RSS feed: {error3}")
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2
            else:
                logging.error("Max attempts reached for fetching RSS feed.")
                raise
    raise RuntimeError("Unreachable code reached in fetch_rss_feed")


def add_movie_to_radarr(imdb_id: str, folder: str, quality: str, max_attempts: int = 3, initial_delay: int = 5) -> \
        Tuple[List, List, List, List]:
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            result = radarr.add_multiple_movies([imdb_id], folder, quality)
            added, exists, invalid, excluded = cast(Tuple[List, List, List, List], result)
            logging.info(
                f"✅ IMDb ID {imdb_id} - Added: {added}, Exists: {exists}, Invalid: {invalid}, Excluded: {excluded}"
            )
            return added, exists, invalid, excluded
        except Exception as error4:
            logging.error(f"Attempt {attempt}: Error adding movie {imdb_id} to Radarr: {error4}")
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2
            else:
                logging.error(f"Max attempts reached for IMDb ID {imdb_id}. Skipping.")
                return [], [], [imdb_id], []
    raise RuntimeError("Unreachable code reached in add_movie_to_radarr")


# -----------------------------------------------------------------------------
# Functions for Script Execution
# -----------------------------------------------------------------------------

def run_script():
    """
    Fetch the RSS feed, process movies, and send matching ones to Radarr.
    """
    global total_movies_added, total_movies_exists, total_movies_invalid, total_movies_excluded, running
    match_regex, not_match_regex = load_regex_patterns(config_model)
    # Load GUIDs
    if DEBUG_MODE:
        scanned_guids_set = set()
    else:
        if os.path.exists(GUID_TRACK_FILE):
            with open(GUID_TRACK_FILE, "r", encoding="utf-8") as f:
                scanned_guids_set = set(f.read().splitlines())
        else:
            scanned_guids_set = set()

    try:
        response = fetch_rss_feed(RSS_FEED_URL)
        root = ET.fromstring(response.content)
        total_items = len(root.findall("./channel/item"))
        existing_guids_count = sum(
            1 for item in root.findall("./channel/item")
            if item.find("guid") is not None and item.find("guid").text.split("/")[-1] in scanned_guids_set
        )

        logging.info(
            f"✅ Successfully fetched and parsed RSS feed ({len(response.content)} bytes) with {total_items} items."
        )
        logging.info(f"🔄 {existing_guids_count} of {total_items} items were previously processed.")
    except Exception as error5:
        logging.error(f"❌ Failed to fetch or parse RSS feed: {error5}. Skipping this run.")
        return

    ns = {"nntmux": "https://nzbfinder.ws/rsshelp/"}
    new_guids = []

    for item in root.findall("./channel/item"):
        title_elem = item.find("title")
        title = title_elem.text if title_elem is not None else ""
        imdb_id_elem = item.find("nntmux:attr[@name='imdb']", ns)
        imdb_id = imdb_id_elem.get("value") if imdb_id_elem is not None else None
        guid_elem = item.find("guid")
        guid_full = guid_elem.text if guid_elem is not None else None
        guid = guid_full.split("/")[-1] if guid_full else None

        if not guid:
            continue
        if not DEBUG_MODE and guid in scanned_guids_set:
            continue

        if filter_title(title, match_regex, not_match_regex):
            logging.info(f"✅ MATCHED: {title}")
            if imdb_id:
                imdb_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
                # Ensure title is a proper string before appending
                imdb_ids_to_add.append((imdb_id, title or "Unknown Title"))
        else:
            logging.info(f"❌ NOT MATCHED: {title}")

        new_guids.append(guid)

    if imdb_ids_to_add:
        logging.info(f"🎬 Processing {len(imdb_ids_to_add)} movies to add to Radarr...")
        radarr.respect_list_exclusions_when_adding()  # Respect exclusion lists

        total_added = total_exists = total_invalid = total_excluded = 0
        for imdb_id, movie_title in imdb_ids_to_add:
            added, exists, invalid, excluded = add_movie_to_radarr(imdb_id, MOVIE_FOLDER, QUALITY_PROFILE)
            total_added += len(added)
            total_exists += len(exists)
            total_invalid += len(invalid)
            total_excluded += len(excluded)
            # Update cumulative totals
            total_movies_added += len(added)
            total_movies_exists += len(exists)
            total_movies_invalid += len(invalid)
            total_movies_excluded += len(excluded)

            # Log invalid movie responses to a separate file
            if invalid:
                with open(INVALID_MOVIE_LOG_FILE, "a", encoding="utf-8") as f_invalid:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f_invalid.write(f"{timestamp} - {movie_title} - {imdb_id}\n")
                    logging.info(f"**** {movie_title} - {imdb_id} ****\n")

        logging.info(
            f"📊 Summary for this run: Added: {total_added}, Exists: {total_exists}, Invalid: {total_invalid}, Excluded: {total_excluded}"
        )

    if not DEBUG_MODE:
        final_guids = (new_guids + list(scanned_guids_set))[:MAX_STORED_GUIDS]
        with open(GUID_TRACK_FILE, "w", encoding="utf-8") as f:
            for guid in final_guids:
                f.write(guid + "\n")

    logging.info(
        f"📈 Cumulative Summary: Total Added: {total_movies_added}, Total Exists: {total_movies_exists}, "
        f"Total Invalid: {total_movies_invalid}, Total Excluded: {total_movies_excluded}"
    )


def listen_for_manual_run():
    """
    Continuously listens for 'Ctrl + R' to signal a manual execution.
    """
    global running
    while running:
        keyboard.wait("ctrl+r")
        manual_run_event.set()


def run_countdown(total_seconds: int) -> bool:
    forced = os.environ.get("FORCE_INTERACTIVE", "0") == "1"
    interactive = forced or sys.stdout.isatty()
    if not interactive:
        next_run_time = datetime.datetime.now() + datetime.timedelta(seconds=total_seconds)
        logging.info(f"⏳ Next run scheduled at: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
    start_time = time.time()
    while running:
        if manual_run_event.is_set():
            return True
        elapsed = time.time() - start_time
        remaining = total_seconds - int(elapsed)
        if remaining <= 0:
            break
        if interactive:
            mins, secs = divmod(remaining, 60)
            sys.stdout.write("\r" + " " * 80)
            sys.stdout.flush()
            sys.stdout.write(f"\r⏳ Next run in {mins}m {secs}s (Press 'Ctrl + R' to run now)")
            sys.stdout.flush()
        else:
            # In non-interactive mode, you might choose to not print anything or log periodically.
            pass
        time.sleep(1)
    if interactive:
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
    return False


# -----------------------------------------------------------------------------
# Unit Testing (for extensibility)
# -----------------------------------------------------------------------------

def test_filter_title():
    test_regex_include = re.compile("movie", re.IGNORECASE)
    test_regex_exclude = re.compile("bad", re.IGNORECASE)
    assert filter_title("This is a Movie", test_regex_include, None) is True
    assert filter_title("This is not a film", test_regex_include, None) is False
    assert filter_title("This is a Movie but bad", test_regex_include, test_regex_exclude) is False
    assert filter_title("", test_regex_include, test_regex_exclude) is False
    logging.info("✅ All filter_title tests passed.")


def run_unit_tests():
    """Runs unit tests for key functions."""
    test_filter_title()


# -----------------------------------------------------------------------------
# Main Loop
# -----------------------------------------------------------------------------

def main():
    global running
    if USE_KEYBOARD:
        keyboard_thread = threading.Thread(target=listen_for_manual_run, daemon=True)
        keyboard_thread.start()
    else:
        logging.info("⌨️ Keyboard functionality is disabled (USE_KEYBOARD = False)")

    logging.info("🚀 Running script immediately on startup...")
    run_script()

    while running:
        # Clear any leftover countdown text before starting a new countdown cycle.
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

        triggered = run_countdown(EXECUTION_INTERVAL * 60)
        if not running:
            break
        if triggered:
            manual_run_event.clear()
            sys.stdout.write("\n")
            sys.stdout.flush()
            logging.info("🟢 Manual execution triggered!")
            run_script()
        else:
            run_script()

    logging.info("Script terminated gracefully.")


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_unit_tests()
        sys.exit(0)
    main()
