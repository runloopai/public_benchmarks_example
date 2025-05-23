import asyncio
import argparse
from dataclasses import dataclass
from typing import Optional
from runloop_api_client import AsyncRunloop
from runloop_api_client.types import ScenarioRetrieveResponse
from runloop_api_client.types.scenario_run_view import ScenarioRunView
from runloop_api_client.lib.polling import PollingConfig

CONCURRENT_RUNS = 50
semaphore = asyncio.Semaphore(CONCURRENT_RUNS)

@dataclass
class ScenarioRunResult:
    scenario: ScenarioRetrieveResponse
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
    parser = argparse.ArgumentParser(description='Run scenarios with reference solutions')
    parser.add_argument('--benchmark-id', type=str, help='Benchmark ID to run all scenarios from')
    parser.add_argument('--scenario-id', type=str, help='Single scenario ID to run')
    parser.add_argument('--scenario-name', type=str, help='Single scenario name to run')
    parser.add_argument('--keep-devbox', action='store_true', help='Keep devbox running after scoring for manual inspection and debugging')
    parser.add_argument('--force-clear-running-devboxes', action='store_true', help='Force shutdown all running devboxes before running the benchmark/scenario')
    args = parser.parse_args()

    if not args.benchmark_id and not args.scenario_id and not args.scenario_name:
        parser.error("Either --benchmark-id or --scenario-id or --scenario-name must be provided")

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
                attempt_scenario_run_with_golden_patch(runloop, id, benchmark_run.id, args.keep_devbox)
                for id in benchmark_run.pending_scenarios
            ]
        )

        # Step 3. We collect the results. Runloop Scorers all result in a score from 0 to 1.0
        successes = [r for r in results if r.run_completed]
        failures = [r for r in results if not r.run_completed]

        print(f"Successes: {len(successes)}")
        for result in successes:
            print(f"{result.scenario.id} {result.scenario.name}: {result.score}")

        for failure in failures:
            print(f"Failed to Run {failure.scenario.id} {failure.scenario.name}: {failure.error}")

        # Print size of success + score == 1.0
        success_and_passing = [
            r for r in successes if r.score == 1.0
        ]
        print(f"Run Completed and Successful (score=1.0): {len(success_and_passing)}")
        success_and_failing = [
            r for r in successes if r.score != 1.0
        ]
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
        result = await attempt_scenario_run_with_golden_patch(runloop, scenario_id, None, args.keep_devbox)
        if not result.run_completed:
            print(f"Error running scenario: {result.error}")
        else:
            print(f"Scenario {result.scenario.id} {result.scenario.name} completed with score: {result.score}")            
        


async def attempt_scenario_run_with_golden_patch(
    runloop: AsyncRunloop,
    scenario_id: str,
    benchmark_run_id: str | None,
    keep_devbox: bool = False,
) -> ScenarioRunResult:
    scenario = await runloop.scenarios.retrieve(scenario_id)
    try:
        async with semaphore:
            run = await run_scenario_with_reference_solution(
                runloop, scenario, benchmark_run_id, keep_devbox
            )
            return ScenarioRunResult(scenario=scenario, run=run)
    except Exception as e:
        return ScenarioRunResult(scenario=scenario, error=str(e))


async def run_scenario_with_reference_solution(
    runloop: AsyncRunloop,
    scenario: ScenarioRetrieveResponse,
    benchmark_run_id: str | None,
    keep_devbox: bool = False,
) -> ScenarioRunView:
    print(f"Running scenario: {scenario.id} {scenario.name}")
    print(f"View Scenario Info at: https://platform.runloop.ai/scenarios/{scenario.id}")

    # Step 1. We start a scenario run which will create a devbox and prepare the environment for testing
    scenario_run = await runloop.scenarios.start_run_and_await_env_ready(
        scenario_id=scenario.id,
        benchmark_run_id=benchmark_run_id,
        polling_config=PollingConfig(max_attempts=60 * 5),
    )

    print(f"View Run Results at: https://platform.runloop.ai/scenarios/{scenario.id}/runs/{scenario_run.id}")

    # Step 2. Run SWE agent to solve the scenario
    # First write the problem statement to a file
    await runloop.devboxes.write_file_contents(
        id=scenario_run.devbox_id,
        file_path="/home/user/problem_statement.txt",
        contents=scenario.input_context.problem_statement,
    )

    prepare_swe_agent_command = await runloop.devboxes.execute_sync(
        id=scenario_run.devbox_id,
        command=" git clone https://github.com/SWE-agent/SWE-agent.git && cd SWE-agent && uv venv && source .venv/bin/activate && uv pip install -e ."        
    )
    if prepare_swe_agent_command.exit_status != 0:
        raise Exception(f"Failed to prepare SWE agent. Exit status: {prepare_swe_agent_command.exit_status}")

    OPENAI_API_KEY = "<your-openai-api-key>"
    SWE_AGENT_COMMAND = f"""
    cd SWE-agent && source .venv/bin/activate && export OPENAI_API_KEY={OPENAI_API_KEY} && sweagent run   \
	--agent.model.name=gpt-4o  \
	 --agent.model.per_instance_cost_limit=2.00 \
	--env.repo.type=preexisting \
	--env.repo.repo_name="testbed"  \
	--env.deployment.type=local \
	--agent.model.api_key=$OPENAI_API_KEY \
	--problem_statement.path="/home/user/problem_statement.txt" \
	--problem_statement.type=text_file
    """
    execution = await runloop.devboxes.execute_async(scenario_run.devbox_id, command=SWE_AGENT_COMMAND)
    final_execution_state = await runloop.devboxes.executions.await_completed(execution_id=execution.execution_id, devbox_id=scenario_run.devbox_id, polling_config=PollingConfig(max_attempts=60 * 5))
    print(f"Final execution state: {final_execution_state.exit_status}")
    print(f"Final execution output: {final_execution_state.stdout}")
    if final_execution_state.exit_status != 0:
        raise Exception(f"SWE agent failed to run. Exit status: {final_execution_state.exit_status}")
    # -------------------------------------------

    # Step 3. We score the scenario. This will automatically run all scorers for the scenario against the current state of the devbox.
    result = await runloop.scenarios.runs.score_and_await(
        id=scenario_run.id,
        polling_config=PollingConfig(max_attempts=60 * 5),
    )
    score = result.scoring_contract_result.score if result.scoring_contract_result else None
    print(
        f"Scoring result: id={result.id} score={score}"
    )    

    if not keep_devbox:
        # Step 4. We complete the scenario run. This will delete the devbox and clean up the environment.
        await runloop.scenarios.runs.complete(id=scenario_run.id)
    else:
        print(f"Keeping devbox {scenario_run.devbox_id} running for manual inspection")

    return result


if __name__ == "__main__":
    print("Starting...")
    asyncio.run(main())
