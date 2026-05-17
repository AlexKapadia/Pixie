# {{TOOL_NAME}}

*{{DESCRIPTION}}*

## What it does

Pipes an uploaded file through an external CLI (`ffmpeg` by default)
and returns the resulting file. Use this template as the starting point
for tools that wrap any command-line program: tesseract, pandoc,
imagemagick, yt-dlp, etc.

## Install

```sh
cd tools/{{TOOL_ID}}
uv sync
```

## System dependencies

The wrapped binary must be on PATH. Check with:

```sh
# macOS / Linux
which ffmpeg
# Windows (PowerShell)
Get-Command ffmpeg
```

If missing:

| OS | Install |
|---|---|
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` or download from <https://ffmpeg.org/> |

The `pixie-doctor` skill also checks for it. The tool itself uses
`shutil.which("ffmpeg")` at request time and returns a friendly
"binary missing" message rather than a 500.

## Swap in a different binary

Edit `src/{{PACKAGE}}/runner.py`:

```python
CLI_NAME = "tesseract"  # or pandoc, yt-dlp, etc.
def build_command(source, output, extra_args):
    return [CLI_NAME, str(source), str(output.with_suffix("")), *shlex.split(extra_args)]
```

## Run standalone

```sh
uv run python main.py --port 8001
```

## Inputs

| Key | Type | Description |
|---|---|---|
| `source` | file | The file to process. |
| `extra_args` | text | Optional extra arguments appended to the CLI invocation. |

## Outputs

| Key | Type | Description |
|---|---|---|
| `result` | file | The CLI's output file (base64-wrapped). |

## External services / API keys

None.
