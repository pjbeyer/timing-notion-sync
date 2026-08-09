# ⏱️ Timing to Notion Sync

Automatically sync your daily time tracking data from Timing.app to a Notion database for visualization and reporting. Perfect for creating daily/weekly/monthly time tracking charts and reports in Notion.

## ✨ Features

- 🔄 Automatic sync every 15 minutes (at :00, :15, :30, :45)
- 📊 Groups time by project with full hierarchy support
- 🕐 Timezone-aware date handling
- 🔐 Secure token storage via environment variables or macOS Keychain

### Enhanced Features (Optional)

- 📝 **Entry-level details** - Sync individual time entries with titles and notes
- 📱 **ScreenTime integration** - Capture macOS app usage data alongside Timing
- 📈 **Extended metrics** - Entry counts, top activities, active hours

## 📋 Prerequisites

- macOS (uses launchd for scheduling)
- Python 3 (system Python is fine)
- [Timing.app](https://timingapp.com) Pro account (for API access)
- Notion account with API access

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/timing-notion-sync.git
   cd timing-notion-sync
   ```

2. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

3. **Get your API tokens**
   
   **Timing API Token:**
   - Open Timing.app → Preferences → Web API
   - Enable API and copy your token
   
   **Notion API Token:**
   - Go to [Notion Integrations](https://www.notion.so/my-integrations)
   - Create a new integration
   - Copy the Internal Integration Token
   
   **Notion Database ID:**
   - Create a new Notion database or use existing
   - Share it with your integration
   - Copy the database ID from the URL: `notion.so/yourworkspace/[DATABASE_ID]?v=...`

4. **Configure your tokens**
   
   Edit the `.env` file and add your tokens:
   ```
   TIMING_API_TOKEN=your_timing_token_here
   NOTION_API_TOKEN=your_notion_token_here  
   NOTION_DATABASE_ID=your_database_id_here
   ```

5. **Set up your Notion database**
   
   Required properties (exact names):
   - `Project` (Title) - The project name
   - `Date` (Date) - The date of the time entry
   - `Duration` (Text) - Time in H:MM:SS format
   - `Hours` (Number) - Decimal hours for calculations
   - `Last Sync` (Date) - Timestamp of when the entry was last synced
   
   Optional formula property for readable time:
   - `Readable Time` (Formula) - Converts hours to "Xh Ym Zs" format:
   ```
   format(floor(prop("Hours") * 3600 / 3600)) + "h " +
   format(floor(mod(prop("Hours") * 3600, 3600) / 60)) + "m " +
   format(floor(mod(prop("Hours") * 3600, 60))) + "s"
   ``` 

6. **Install and start the sync**
   ```bash
   ./install.sh
   ```

### macOS Keychain Integration (Optional)

For enhanced security, store your API tokens in macOS Keychain instead of a `.env` file. This allows the sync to run via launchd without storing credentials in plaintext.

**Initial setup** (requires [1Password CLI](https://developer.1password.com/docs/cli/)):
```bash
./refresh-secrets.sh
```

**Manual setup** (without 1Password):
```bash
security add-generic-password -a "$USER" -s "timing-notion-sync-timing-token" -w "YOUR_TIMING_TOKEN"
security add-generic-password -a "$USER" -s "timing-notion-sync-notion-token" -w "YOUR_NOTION_TOKEN"
```

When Keychain credentials are present, `run-sync.sh` uses them automatically instead of the `.env` file.

## 🚀 Enhanced Sync Features

The sync script supports optional enhanced data collection beyond basic project totals.

### Entry-Level Details

Capture individual time entries with titles and notes:

```bash
# In .env file
SYNC_ENTRIES=true
```

**Required Notion properties:**
- `Entry Count` (Number) - Number of time entries for the project
- `Top Entries` (Text) - Summary of top activities by duration

### Custom Fields Propagation

Propagate Timing entry `custom_fields` (device-scoped enrichment markers, e.g. from the Dayflow enrichment pipeline) into each entry's Notion page content:

```bash
# In .env — only effective when SYNC_ENTRIES=true
SYNC_CUSTOM_FIELDS=true
```

- Fields render as an **italic green sub-paragraph** under each entry bullet, in `key: value` pairs.
- Only fields **present on an entry** are shown; entries without `custom_fields` are unchanged (nothing is required on all entries).
- They appear in **page content only**, never in the visible `Project`/`Duration`/`Date` columns, so invoice/timesheet views stay clean.
- **Read-only**: the sync reads `custom_fields` and never writes them back to Timing (write-back is the separate enrichment pipeline).

### ScreenTime Integration

Capture macOS app usage data alongside Timing:

```bash
# In .env
SYNC_SCREENTIME=true
SCREENTIME_SOURCE=timing  # "timing" (default, FDA-free) or "knowledgec"
SCREENTIME_TOP_APPS=5     # Number of top apps to include
```

**Data source (`SCREENTIME_SOURCE`):**

- `timing` (default): reads Timing.app's own SQLite `AppActivity` table
  (`~/Library/Application Support/info.eurocomp.Timing2/SQLite.db`). This is
  **FDA-free** — it works under launchd/cron without Full Disk Access — and
  adds per-`localDeviceID` scoping so only this Mac's usage is reported.
- `knowledgec`: reads Apple's `knowledgeC.db`. This **requires Full Disk
  Access** and is blocked for launchd/cron processes (TCC grants per
  executable); prefer `timing`.

**Required Notion properties:**
| Property | Type | Description |
|----------|------|-------------|
| Active Hours | Number | Total active screen time |
| Screen Events | Number | Number of app usage events |
| Top Apps | Text | Summary of most-used apps |

If the source is unavailable (e.g. DB not found), ScreenTime sync is skipped gracefully.

### Idle Handling

The sync skips when the system has been idle longer than `IDLE_THRESHOLD_SECONDS` (default 300s / 5 minutes), so a manual run while idle won't duplicate work. To sync regardless of idle state (e.g. so a launchd sync updates Notion even when the machine is idle):

```bash
# In .env
SYNC_WHEN_IDLE=true
```

### Notion Database Schema

**Basic properties (required):**
| Property | Type | Description |
|----------|------|-------------|
| Project | Title | Project name with hierarchy |
| Date | Date | Entry date |
| Duration | Text | H:MM:SS format |
| Hours | Number | Decimal hours |
| Last Sync | Date | Sync timestamp |

**Enhanced properties (optional):**
| Property | Type | Description |
|----------|------|-------------|
| Entry Count | Number | Time entries per project |
| Top Entries | Text | Top activities summary |
| Active Hours | Number | ScreenTime active hours |
| Screen Events | Number | App usage event count |
| Top Apps | Text | Most-used apps summary |

## 🔧 Configuration

### Creating Charts in Notion
- Add a Chart view to your database
- Set visualization to show by `Project`
- Set each slice to `Hours` → `Values`

### Sync Frequency
By default, syncs run at :00, :15, :30, and :45 of every hour. To modify:
1. Edit `com.timing-notion-sync.plist`
2. Adjust the `StartCalendarInterval` entries
3. Reload: `launchctl unload ~/Library/LaunchAgents/com.timing-notion-sync.plist && launchctl load ~/Library/LaunchAgents/com.timing-notion-sync.plist`

### Project Grouping
The sync automatically:
- Groups all time entries by project
- Preserves full project hierarchy (e.g., "Work > Client A > Project X")
- Sums durations for each project per day
- Updates existing entries or creates new ones

### Multi-Database Routing (Optional)

Sync different Timing project roots/folders to **different Notion databases**:

```bash
# In .env
PROJECT_DB_MAP={"Work":"<work_db_id>","Family":"<family_db_id>","Consulting":"<consulting_db_id>"}
```

The top-level folder of each project's hierarchy path is used as the routing key:
- `Work > Client A > Project X` → `Work` → the Work database
- `Family > Groceries` → `Family` → the Family database
- Any project whose root isn't in the map falls back to `NOTION_DATABASE_ID`

Each target database should have the same base schema (`Project`, `Date`, `Duration`, `Hours`, `Last Sync`) plus any enhanced properties you enable. Idempotency is scoped per `(database, date, project)`, so the same project always lands in one database and re-runs update rather than duplicate.

If `PROJECT_DB_MAP` is unset or not valid JSON, all projects use `NOTION_DATABASE_ID` (backward compatible).

### Multi-Workspace (Optional)

Route project folders to **different Notion workspaces** (e.g. GSD personal vs. Flex/work vs. consulting), each with its own Notion API token:

```bash
# In .env
WORKSPACES={"gsd":{"token_env":"NOTION_API_TOKEN","databases":{"Family":"<family_db_id>"}},"flex":{"token_env":"NOTION_API_TOKEN_FLEX","databases":{"Work":"<work_db_id>","Consulting":"<consult_db_id>"}}}
WORKSPACE_MAP={"Family":"gsd","Work":"flex","Consulting":"flex"}
```

- `WORKSPACES` is the registry: each entry has a `token_env` (the env var holding that workspace's Notion API token) and a `databases` map from project folder to database ID.
- `WORKSPACE_MAP` assigns each project **root folder** to a workspace. A folder not listed falls back to the default workspace (`NOTION_API_TOKEN` + `NOTION_DATABASE_ID` / `PROJECT_DB_MAP`).
- Provide the extra tokens (e.g. `NOTION_API_TOKEN_FLEX`) in `.env` or via `run-sync.sh`/Keychain.
- **Routing is structural and fail-closed**: the folder→workspace mapping is fixed by config, so a `Family` project can never resolve to the Flex workspace and vice versa. Never set a `token_env` to a credential that should not write that folder's data.
- Idempotency is scoped per `(workspace, database, date, project)`.

## 📊 Usage

### Check sync status
```bash
launchctl list | grep timing-notion-sync
```
- Exit code `0` = running successfully
- Exit code `1` = error occurred

### View recent syncs
```bash
tail -20 logs/sync.log
```

### Manual sync
```bash
python3 timing-notion-sync.py
```

**Note:** If you get a "No module named 'dotenv'" error, install the dependencies:

For most users:
```bash
pip3 install --user requests python-dotenv
```

For macOS with Homebrew Python (if you get "externally-managed-environment" error):
```bash
pip3 install --user --break-system-packages requests python-dotenv
```

### Stop syncing
```bash
./uninstall.sh
```

## 🚨 Troubleshooting

### Common Issues

**"No module named requests" error**
- Your Python environment is missing dependencies
- Run: `pip3 install --user requests python-dotenv`

**No data syncing**
- Verify Timing.app has data for today
- Check timezone settings (script uses local timezone)
- Ensure API tokens are valid

**ScreenTime "authorization denied" error**
- Full Disk Access not enabled for your terminal
- System Settings → Privacy & Security → Full Disk Access
- Add Terminal.app, iTerm, or your preferred terminal
- Note: launchd agents may need separate Full Disk Access configuration

**Enhanced properties not syncing**
- Notion database missing required properties
- Add the optional properties listed in the Enhanced Sync section
- Script falls back to basic sync if properties don't exist

### Error Handling
When sync fails:
- Error file created on Desktop: `TIMING_SYNC_ERROR_[timestamp].txt`
- Detailed error logged in `logs/error.log`
- Sync continues running on schedule

### Debug Mode
Run manually to see detailed output:
```bash
python3 timing-notion-sync.py
```

## 🔐 Security

- **Never commit `.env` file** - it contains sensitive API tokens
- API tokens are stored locally in `.env` file
- Consider rotating tokens periodically
- The `.gitignore` file excludes sensitive data

## 📁 File Structure

```
timing-notion-sync/
├── timing-notion-sync.py                # Main sync script (Timing + ScreenTime)
├── run-sync.sh                          # Wrapper for Keychain credentials
├── refresh-secrets.sh                   # 1Password → Keychain sync
├── com.timing-notion-sync.plist.template # launchd template
├── install.sh                           # Installation script
├── uninstall.sh                         # Uninstall script
├── .env.example                         # Configuration template
├── .gitignore                           # Excludes sensitive files
├── logs/                                # Error logs (auto-created)
└── README.md                            # This file
```

## 🤝 Contributing

Feel free to open issues or submit pull requests. Please ensure you don't commit any personal API tokens or data.

## 👨‍💻 Developer Notes

If you're developing this tool with a virtual environment:

### Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
```

### Running manually
```bash
# From project directory
.venv/bin/python3 timing-notion-sync.py

# Or activate venv first
source .venv/bin/activate
python3 timing-notion-sync.py
```

### Testing after changes
```bash
# Reload launchd service to test automation
launchctl unload ~/Library/LaunchAgents/com.timing-notion-sync.plist
launchctl load ~/Library/LaunchAgents/com.timing-notion-sync.plist
```

**Note:** The launchd service uses system Python, not your venv. To test with your venv, run manually.
