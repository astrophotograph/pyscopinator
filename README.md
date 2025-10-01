# Scopinator

A library for controlling telescopes (initially Seestars).

## Example commands

uv run scopinator status
uv run scopinator discover
uv run scopinator version
uv run scopinator device-state --all --host 192.168.42.41
uv run scopinator device-state --all --json --host 192.168.42.41
uv run scopinator device-state --all --json --host 192.168.42.41 | fx
uv run scopinator capture-video --host 192.168.42.41 --duration 10
uv run scopinator monitor
uv run scopinator monitor --host 192.168.42.41
uv run scopinator monitor --host 192.168.42.41 --json
uv run scopinator monitor --host 192.168.42.41 -i pi_get_time
uv run scopinator stream-images --host 192.168.42.41 --show-events
uv run scopinator stream-images --host 192.168.42.41 --compact
uv run scopinator stream-images --host 192.168.42.41 --compact --scenery --save scenery.mp4
uv run scopinator stream-images --host 192.168.42.41 --compact --scenery --save scenery.mp4 --save-video
uv run scopinator stream-images --host 192.168.42.41 --compact --save scenery.mp4 --save-video --count 50 --scenery
uv run scopinator repl
SCOPINATOR_DEBUG=false  uv run scopinator repl 
SCOPINATOR_TRACE=true SCOPINATOR_DEBUG=true uv run scopinator stream-images --host 192.168.42.41 --compact

## Versioning

This project uses [CalVer](https://calver.org/) versioning in a SemVer-compatible format:

**Format: `YYYY.MM.PATCH`**

- `YYYY`: Full year (e.g., 2025)
- `MM`: Month without zero-padding (e.g., 8 for August)
- `PATCH`: Patch version for bug fixes within the month (starts at 0)

This format is compatible with Semantic Versioning where:
- `YYYY` acts as the MAJOR version
- `MM` acts as the MINOR version
- `PATCH` acts as the PATCH version

Example: `2025.8.0` means the first release in August 2025.

