import asyncio
import argparse
from dataclasses import dataclass
from typing import Optional
from runloop_api_client import AsyncRunloop
from runloop_api_client.types import ScenarioView
from runloop_api_client.types.scenario_run_view import ScenarioRunView
from runloop_api_client.lib.polling import PollingConfig

CONCURRENT_RUNS = 50
semaphore = asyncio.Semaphore(CONCURRENT_RUNS)
POLLING_INTERVAL_SECONDS = 5
# 10 minutes
DEVBOX_MAX_ATTEMPTS = int(60 * 10 / POLLING_INTERVAL_SECONDS)
# 30 minutes
SCORING_MAX_ATTEMPTS = int(60 * 15 / POLLING_INTERVAL_SECONDS)


@dataclass
class ScenarioRunResult:
    scenario: ScenarioView
    run: Optional[ScenarioRunView] = None
    error: Optional[str] = None

    @property
    def run_completed(self) -> bool:
        return self.run is not None and self.error is None

    @property
    def score(self) -> Optional[float]:
        if self.run and self.run.scoring_contract_result:
            return self.run.scoring_contract_result.score
        return None


async def main():
    parser = argparse.ArgumentParser(
        description="Run scenarios with reference solutions"
    )
    parser.add_argument(
        "--benchmark-id", type=str, help="Benchmark ID to run all scenarios from"
    )
    parser.add_argument("--scenario-id", type=str, help="Single scenario ID to run")
    parser.add_argument("--scenario-name", type=str, help="Single scenario name to run")
    parser.add_argument(
        "--keep-devbox",
        action="store_true",
        help="Keep devbox running after scoring for manual inspection and debugging",
    )
    parser.add_argument(
        "--force-clear-running-devboxes",
        action="store_true",
        help="Force shutdown all running devboxes before running the benchmark/scenario",
    )
    args = parser.parse_args()

    if not args.benchmark_id and not args.scenario_id and not args.scenario_name:
        parser.error(
            "Either --benchmark-id or --scenario-id or --scenario-name must be provided"
        )

    runloop = AsyncRunloop()

    # Optionally, shutdown all running devboxes to ensure no abandoned resources
    if args.force_clear_running_devboxes:
        devboxes = await runloop.devboxes.list(status="running", limit=1000)
        print(f"Found {len(devboxes.devboxes)} running devboxes. Forcing shutdown...")
        for devbox in devboxes.devboxes:
            await runloop.devboxes.shutdown(id=devbox.id)
        print("All devboxes have been shut down.")

    # Run full benchmark
    if args.benchmark_id:
        benchmark_id = args.benchmark_id

        # Step 1. We start a benchmark run which keeps track of all the scenarios that we need to run for that benchmark
        # Benchmarks are a collection of scenarios that together test a specific set of skills. For example, the SWE-bench Verified benchmark is a collection of scenarios that test solving python problems for real world use cases.
        # Benchmark runs are used to track the results of running an agent against a benchmark.

        benchmark = await runloop.benchmarks.retrieve(benchmark_id)

        benchmark_run = await runloop.benchmarks.start_run(
            benchmark_id=benchmark_id,
        )

        print(f"Benchmark Run: {benchmark_run.id} {benchmark_run.name}")

        # Step 2. We run each scenario in parallel
        # A Scenario is a single problem that we want to solve. For example, a single row of the SWE-bench Verified dataset is a scenario.
        # A Scenario is comprised of a test environment specification, a set of inputs that comprise the problem statement and context given to an agent, and a set of scorers to evaluate the quality of the solution
        # A Scenario Run is a single run of a scenario. It is comprised of a live devbox that is used to test the solution and runs all the scorers against the solution.
        results = await asyncio.gather(
            *[
                attempt_scenario_run_with_golden_patch(
                    runloop, id, benchmark_run.id, args.keep_devbox
                )
                for id in benchmark.scenario_ids
            ]
        )

        await runloop.benchmarks.runs.complete(id=benchmark_run.id)

        # Step 3. We collect the results. Runloop Scorers all result in a score from 0 to 1.0

        # Filter out None results
        results = [r for r in results if r is not None]

        successes = [r for r in results if r.run_completed]
        failures = [r for r in results if not r.run_completed]

        print(f"Successes: {len(successes)}")
        for result in successes:
            print(f"{result.scenario.id} {result.scenario.name}: {result.score}")

        for failure in failures:
            print(
                f"Failed to Run {failure.scenario.id} {failure.scenario.name}: {failure.error}"
            )

        # Print size of success + score == 1.0
        success_and_passing = [r for r in successes if r.score == 1.0]
        print(f"Run Completed and Successful (score=1.0): {len(success_and_passing)}")
        success_and_failing = [r for r in successes if r.score != 1.0]
        print(f"Run Completed and Failed (score!=1.0): {len(success_and_failing)}")
        print(f"Failures: {len(failures)}")
    else:
        scenario_id: str | None = None
        if args.scenario_id:
            scenario_id = args.scenario_id
        elif args.scenario_name:
            # We search for the public scenario by name
            scenarios = await runloop.scenarios.list_public(name=args.scenario_name)
            if len(scenarios.scenarios) == 0:
                raise ValueError(f"Scenario with name {args.scenario_name} not found")
            scenario_id = scenarios.scenarios[0].id

        # Run single scenario
        if scenario_id is None:
            raise ValueError("No scenario ID found")
        result = await attempt_scenario_run_with_golden_patch(
            runloop, scenario_id, None, args.keep_devbox
        )
        if result is None:
            return None
        if not result.run_completed:
            print(f"Error running scenario: {result.error}")
        else:
            print(
                f"Scenario {result.scenario.id} {result.scenario.name} completed with score: {result.score}"
            )


async def attempt_scenario_run_with_golden_patch(
    runloop: AsyncRunloop,
    scenario_id: str,
    benchmark_run_id: str | None,
    keep_devbox: bool = False,
) -> ScenarioRunResult | None:
    async with semaphore:
        scenario: ScenarioView | None = None
        try:
            scenario = await runloop.scenarios.retrieve(scenario_id)
        except Exception as e:
            print(f"Error retrieving scenario: {e}")
            return None

        try:
            # We run the scenario with the reference solution
            run = await run_scenario_with_reference_solution(
                runloop, scenario, benchmark_run_id, keep_devbox
            )
            return ScenarioRunResult(scenario=scenario, run=run)
        except Exception as e:
            return ScenarioRunResult(scenario=scenario, error=str(e))


async def run_scenario_with_reference_solution(
    runloop: AsyncRunloop,
    scenario: ScenarioView,
    benchmark_run_id: str | None,
    keep_devbox: bool = False,
) -> ScenarioRunView:
    print(f"Running scenario: {scenario.id} {scenario.name}")
    print(f"View Scenario Info at: https://platform.runloop.ai/scenarios/{scenario.id}")

    # Step 1. We start a scenario run which will create a devbox and prepare the environment for testing
    scenario_run = await runloop.scenarios.start_run_and_await_env_ready(
        scenario_id=scenario.id,
        benchmark_run_id=benchmark_run_id,
        polling_config=PollingConfig(
            max_attempts=DEVBOX_MAX_ATTEMPTS,
            interval_seconds=POLLING_INTERVAL_SECONDS,
        ),
    )

    try:
        print(
            f"View Run Results at: https://platform.runloop.ai/scenarios/{scenario.id}/runs/{scenario_run.id}"
        )

        # Step 2. We apply the reference solution to the devbox
        # Replace the below with your own agent code to apply a solution dynamically.
        # You can use the Devbox API to write files to the devbox and execute shell commands.
        # See https://docs.runloop.ai/devboxes/execute-commands
        # and https://docs.runloop.ai/devboxes/files
        # -------------------------------------------
        # Write patch to /home/user/ref.patch
        await runloop.devboxes.write_file_contents(
            id=scenario_run.devbox_id,
            file_path="/home/user/ref.patch",
            # The reference output is the golden patch from the public SWE-bench dataset
            contents=scenario.reference_output or "",
        )

        # Apply patch
        await runloop.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command="cd /testbed && patch -p1 < /home/user/ref.patch",
        )
        # -------------------------------------------

        # Step 3. We score the scenario. This will automatically run all scorers for the scenario against the current state of the devbox.
        result = await runloop.scenarios.runs.score_and_await(
            id=scenario_run.id,
            polling_config=PollingConfig(
                max_attempts=SCORING_MAX_ATTEMPTS,
                interval_seconds=POLLING_INTERVAL_SECONDS,
            ),
        )
        score = (
            result.scoring_contract_result.score
            if result.scoring_contract_result
            else None
        )
        print(f"Scoring result: id={result.id} score={score}")

        if not keep_devbox:
            # Step 4. We complete the scenario run. This will delete the devbox and clean up the environment.
            await runloop.scenarios.runs.complete(id=scenario_run.id)
        else:
            print(
                f"Keeping devbox {scenario_run.devbox_id} running for manual inspection"
            )

        return result
    except Exception as e:
        print(f"Error running scenario: {e}")

        # Ensure we clean up the devbox on error
        if not keep_devbox:
            await runloop.devboxes.shutdown(id=scenario_run.devbox_id)

        raise e


if __name__ == "__main__":
    print("Starting...")
    asyncio.run(main())
