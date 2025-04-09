
# 🎬 NZBFinder to Radarr Automation Script

This Python script automates the process of scanning NZBFinder RSS feeds for new movie releases, filtering them by regex rules, and adding matching movies to Radarr for automatic download.

## 🚀 Features

- ✅ Polls NZBFinder RSS feed at a user-defined interval.
- 🔎 Filters releases using configurable `match_patterns` and `not_match_patterns`.
- 🎯 Adds matched movies to Radarr using the IMDb ID.
- 📋 Tracks processed GUIDs to prevent duplicates.
- ⌨️ Supports manual execution via `Ctrl + R` hotkey.
- 🐳 Docker compatible.
- 📊 Logs movie processing results and errors.
- 🛠 Automatically retries failed requests with exponential backoff.
- 🧪 Built-in unit test for regex filtering.

## 📁 Project Structure

```
.
├── config/
│   ├── .env                 # Environment variables
│   ├── config.yaml          # Script configuration (patterns, intervals, etc.)
│   ├── scanned_guids.txt    # Tracked GUIDs to prevent re-processing
│   └── invalid_movie.log    # Logs movies rejected by Radarr
├── NZBFinder_Copilot.py                  # Main script
├── Dockerfile               # (Optional) Docker setup
└── README.md                # This file
```

## ⚙️ Configuration

### `.env`

Set your API keys and endpoints:

```env
NZBFINDER_API_KEY=your_nzbfinder_api_key
RADARR_URL=http://your-radarr-host:7878
RADARR_API_KEY=your_radarr_api_key
```

### `config.yaml`

Configure match patterns, excluded languages, execution interval, and other behavior:

```yaml
execution_interval: 30  # in minutes
max_stored_guids: 1000
debug_mode: false
debug_logging: false
use_keyboard: true
movie_folder: /data/media/movies
quality_profile: 1080p265
match_patterns:
  - "^(?=.*\b1080p\b)(?=.*\b(?:WEBRip|BluRay)\b)(?=.*\b-Provider\b).*"
not_match_patterns:
  - "(?=.*KOREAN.*)"
  - "(?=.*FRENCH.*)"
  - ...
```

## ▶️ Running the Script

### With Python

```bash
python3 main.py
```

### Manual Execution

Press `Ctrl + R` while the script is running to force an immediate check.

### Unit Test Mode

```bash
python3 main.py --test
```

### In Docker

```bash
docker build -t nzbfinder-radarr .
docker run -d --name nzbfinder-radarr \
  -v $(pwd)/config:/app/config \
  nzbfinder-radarr
```

## 📝 Logging

- `config/script.log` – Main log file.
- `config/invalid_movie.log` – Logs movies that Radarr rejected (likely due to path conflicts or invalid IMDb IDs).
- `config/scanned_guids.txt` – Tracks processed NZB GUIDs to avoid duplication.

## 🧪 Example Output

```
✅ MATCHED: Example.Movie.2025.1080p.WEBRip-Provider
✅ IMDb ID tt1234567 - Added: [], Exists: [[Barbie: Dreamhouse]], Invalid: [], Excluded: []
📊 Summary for this run: Added: 0, Exists: 3, Invalid: 1, Excluded: 0
```

## 🧠 Ideas for Future Enhancements

- GUI using PyQt6
- Integration with Sonarr for TV
- Discord/webhook notifications
- Retry logic for failed IMDb lookups

