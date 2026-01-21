# Runloop API Slim Client

Minimal dependency proof of concept for accessing the Runloop API using async methods and httpx.

## Overview

A lightweight example of Runloop scenarios without the `runloop-api-client` dependency. Uses direct HTTP calls with asyncio and httpx to interact with the Runloop API.

## Features

- Async/await throughout
- Direct API calls using httpx
- Scenario run management
- Devbox file operations
- Async command execution with polling
- Error handling demonstrations

## Setup

```bash
uv venv && source .venv/bin/activate && uv sync
```

Set your API key:
```bash
export RUNLOOP_API_KEY=your_api_key_here
```

## Usage

```bash
./run_public_benchmark_slim.py --scenario-id scn_306iGkB9gDCJwQHv7qYlo
```

## Dependencies

- httpx >= 0.27.0
- Python >= 3.12

## Implementation

The client demonstrates:
- Starting and managing scenario runs
- Waiting for devbox provisioning and readiness
- Writing and reading files in devboxes
- Executing commands asynchronously with completion polling
- Scoring and completing scenario runs
- Error handling for common failure cases
