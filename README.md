# sftp-etl-pipeline

A pluggable, two-phase SFTP ETL pipeline written in Python.

It downloads files from remote SFTP servers, processes them locally (unzip, convert, rename, move/copy), and optionally bulk-loads data into SQL Server using the BCP utility. Network-bound work is deliberately separated from CPU/disk-bound work so that SFTP idle timeouts never interrupt long-running local processing.

## Features

- Two-phase execution (download → process) to avoid SFTP connection timeouts
- Strategy-pattern data sources – add a new source by implementing a simple abstract base class
- Secure credential retrieval via the OS credential store (`keyring`)
- Robust SQLAlchemy engine with connection pooling and automatic retry
- Multi-part ZIP reconstruction with memory-safe streaming
- JSON → CSV/JSON conversion utilities
- Structured start/end logging to SQL Server (with CSV fallback)
- Fully configurable via YAML

## Prerequisites

- Python 3.9+
- Microsoft ODBC Driver 17 (or 18) for SQL Server
- SQL Server Command Line Utilities (`bcp`) – only required for bulk-load sources
- Python packages:

```bash
pip install sqlalchemy paramiko pyodbc tenacity pyYAML keyring
```

## Quick Start

1. Copy `config.yaml` and fill in your SFTP and database settings.  
   **Never store passwords in the YAML file** – register them in the OS credential manager instead.

2. Register the SFTP password in the OS credential store.  
   The service name and username must match the values defined in `config.yaml`.

3. Run:

```bash
python sftp_etl.py <session_id> <processing_path> <mode> [--prefix PREFIX]
```

Supported modes:

| Mode       | Sources executed                          |
|------------|-------------------------------------------|
| `snapshot` | SnapshotSource                            |
| `bulk`     | AdminSource + BulkLoadSource              |
| `flow`     | FlowAdminSource + FlowExtractSource       |
| `all`      | All of the above                          |

Examples:

```bash
python sftp_etl.py 1001 "/tmp/processing" flow
python sftp_etl.py 1002 "/tmp/processing" snapshot --prefix "54205_555"
```

You can also call the pipeline programmatically:

```python
from sftp_etl import sftp_etl
sftp_etl(["1001", "/tmp/processing", "flow"])
```

## Project Layout

```
sftp-etl-pipeline/
├── sftp_etl.py                 # CLI / programmatic entry point
├── config.yaml
├── DataSource/
│   ├── data_source_base.py     # Abstract base class
│   ├── SnapshotSource.py
│   ├── AdminSource.py
│   ├── BulkLoadSource.py
│   ├── FlowAdminSource.py
│   ├── FlowExtractSource.py
│   └── Utilities/
│       ├── file_utils.py
│       └── zipfile_utils.py
├── secureConnectors/
│   ├── sftpify.py              # SFTP context manager
│   ├── db_engine.py            # SQLAlchemy engine factory
│   └── sftp_vault.py           # YAML + keyring
└── LogSuite/
    ├── logging_setup.py
    └── db_reporter.py
```

## Adding a New Data Source

1. Create a new file under `DataSource/` that inherits from `DataSource`.
2. Implement `download_target_files()` and `process_pipeline()`.
3. Register the class name in the `CLASS_MAP` dictionary inside `sftp_etl.py`.
4. Add a corresponding block to `config.yaml`.

## Logging

- Detailed debug logs are written to `<processing_path>/logs/`.
- Start/End telemetry is written to SQL Server via stored procedures `etl.LogStart` / `etl.LogEnd`.
- If the database is unavailable, a CSV fallback is created and later uploaded.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
