# Public Benchmarks Example

This repository contains a script to run public benchmarks using the Runloop API.

## Setup

1. Install `uv` (if not already installed):
See: https://docs.astral.sh/uv/getting-started/installation/
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Sync Dependencies:
```bash
uv sync
```

3. Export your Runloop API Key
You can get an API key from the Runloop dashboard at https://platform.runloop.ai/manage/keys
```bash
export RUNLOOP_API_KEY=<YOUR_API_KEY>
```


## Usage

The script can be run in several ways:

1. Run a specific benchmark:
```bash
uv run run_public_benchmark.py --benchmark-id <BENCHMARK_ID>
```

2. Run a specific scenario by ID:
```bash
uv run run_public_benchmark.py --scenario-id <SCENARIO_ID>
```

3. Run a specific scenario by name:
```bash
uv run run_public_benchmark.py --scenario-name <SCENARIO_NAME>
```

# SWE Bench Examples
1. Run full SWE Bench Verified benchmark:
```bash
uv run run_public_benchmark.py --benchmark-id bmd_2zmp3Mu3LhWu7yDVIfq3m
```

2. Run a specific SWE bench verified scenario by instance ID:
See full list of scenarios at: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
```bash
uv run run_public_benchmark.py --scenario-name astropy__astropy-12907 
```

### Additional Options
- `--keep-devbox`: Keep the devbox running after scoring for manual inspection and debugging
- `--force-clear-running-devboxes`: Force shutdown all running devboxes before running the benchmark/scenario


## Notes
- The script limits concurrent scenario runs to 50

