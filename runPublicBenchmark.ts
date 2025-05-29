import yargs from "yargs";
import { hideBin } from "yargs/helpers";
import { Runloop } from "@runloop/api-client";
import type { Runloop as RunloopTypes } from "@runloop/api-client";

// Maximum number of scenarios to run concurrently
const CONCURRENT_RUNS = 50;

// Types from the Runloop client for strong typing
// These types represent the structure of scenarios, scenario runs, and devboxes
// If you want to see their full structure, check the Runloop API client types
// (or use your IDE's "Go to Definition" feature)
type ScenarioView = RunloopTypes.ScenarioView;
type ScenarioRunView = RunloopTypes.ScenarioRunView;
type DevboxView = RunloopTypes.DevboxView;

// Result of attempting to run a scenario, including the scenario, the run result, and any error
interface ScenarioRunResult {
  scenario: ScenarioView;
  run?: ScenarioRunView;
  error?: string;
}

// Helper to check if a scenario run completed successfully
function runCompleted(result: ScenarioRunResult): boolean {
  return !!result.run && !result.error;
}

// Helper to extract the score from a scenario run result
function score(result: ScenarioRunResult): number | undefined {
  return result.run?.scoring_contract_result?.score;
}

// Main entry point for the CLI tool
async function main() {
  // Parse command-line arguments using yargs
  // Only one of benchmark-id, scenario-id, or scenario-name is required
  const argv = await yargs(hideBin(process.argv))
    .option("benchmark-id", {
      type: "string",
      describe: "Benchmark ID to run all scenarios from",
    })
    .option("scenario-id", {
      type: "string",
      describe: "Single scenario ID to run",
    })
    .option("scenario-name", {
      type: "string",
      describe: "Single scenario name to run",
    })
    .option("keep-devbox", {
      type: "boolean",
      default: false,
      describe:
        "Keep devbox running after scoring for manual inspection and debugging",
    })
    .option("force-clear-running-devboxes", {
      type: "boolean",
      default: false,
      describe:
        "Force shutdown all running devboxes before running the benchmark/scenario",
    })
    .check((argv) => {
      if (
        !argv["benchmark-id"] &&
        !argv["scenario-id"] &&
        !argv["scenario-name"]
      ) {
        throw new Error(
          "Either --benchmark-id or --scenario-id or --scenario-name must be provided"
        );
      }
      return true;
    })
    .conflicts("benchmark-id", ["scenario-id", "scenario-name"])
    .help()
    .parse();

  // Instantiate the Runloop API client
  // This will use your RUNLOOP_API_KEY environment variable for authentication
  const runloop = new Runloop();

  // Optionally, shut down all running devboxes before starting
  // This is useful to avoid resource leaks or conflicts
  if (argv["force-clear-running-devboxes"]) {
    const devboxes = await runloop.devboxes.list({ status: "running" });
    const devboxList: DevboxView[] = [];
    for await (const devbox of devboxes) {
      devboxList.push(devbox);
    }
    console.log(
      `Found ${devboxList.length} running devboxes. Forcing shutdown...`
    );
    for (const devbox of devboxList) {
      await runloop.devboxes.shutdown(devbox.id);
    }
    console.log("All devboxes have been shut down.");
  }

  // If a benchmark ID is provided, run all scenarios in the benchmark
  if (argv["benchmark-id"]) {
    // Start a new benchmark run, which tracks the results of running all scenarios in the benchmark
    const benchmarkId = argv["benchmark-id"] as string;
    const benchmarkRun = await runloop.benchmarks.startRun({
      benchmark_id: benchmarkId,
    });
    console.log(`Benchmark Run: ${benchmarkRun.id} ${benchmarkRun.name}`);

    // Run each scenario in the benchmark in parallel, with a concurrency limit
    // This is similar to Python's asyncio.Semaphore pattern
    const pendingScenarios = benchmarkRun.pending_scenarios;
    const results: ScenarioRunResult[] = [];
    let idx = 0;
    // Helper function to run batches of scenarios concurrently
    async function runNextBatch() {
      const batch: Promise<ScenarioRunResult>[] = [];
      for (
        let i = 0;
        i < CONCURRENT_RUNS && idx < pendingScenarios.length;
        i++, idx++
      ) {
        batch.push(
          attemptScenarioRunWithGoldenPatch(
            runloop,
            pendingScenarios[idx],
            benchmarkRun.id,
            argv["keep-devbox"]
          )
        );
      }
      if (batch.length > 0) {
        const batchResults = await Promise.all(batch);
        results.push(...batchResults);
        await runNextBatch();
      }
    }
    await runNextBatch();

    // Collect and print results
    const successes = results.filter(runCompleted);
    const failures = results.filter((r) => !runCompleted(r));

    console.log(`Successes: ${successes.length}`);
    for (const result of successes) {
      console.log(
        `${result.scenario.id} ${result.scenario.name}: ${score(result)}`
      );
    }
    for (const failure of failures) {
      console.log(
        `Failed to Run ${failure.scenario.id} ${failure.scenario.name}: ${failure.error}`
      );
    }
    const successAndPassing = successes.filter((r) => score(r) === 1.0);
    const successAndFailing = successes.filter((r) => score(r) !== 1.0);
    console.log(
      `Run Completed and Successful (score=1.0): ${successAndPassing.length}`
    );
    console.log(
      `Run Completed and Failed (score!=1.0): ${successAndFailing.length}`
    );
    console.log(`Failures: ${failures.length}`);
  } else {
    // If a scenario ID or name is provided, run just that scenario
    let scenarioId: string | undefined = argv["scenario-id"];
    if (!scenarioId && argv["scenario-name"]) {
      // Look up the scenario by name using the public scenario list
      const scenarios = await runloop.scenarios.listPublic({
        name: argv["scenario-name"],
      });
      const scenarioArr: ScenarioView[] = [];
      for await (const scenario of scenarios) {
        scenarioArr.push(scenario);
      }
      if (scenarioArr.length === 0) {
        throw new Error(
          `Scenario with name ${argv["scenario-name"]} not found`
        );
      }
      scenarioId = scenarioArr[0].id;
    }
    if (!scenarioId) {
      throw new Error("No scenario ID found");
    }
    // Run the single scenario
    const result = await attemptScenarioRunWithGoldenPatch(
      runloop,
      scenarioId,
      undefined,
      argv["keep-devbox"]
    );
    if (!runCompleted(result)) {
      console.log(`Error running scenario: ${result.error}`);
    } else {
      console.log(
        `Scenario ${result.scenario.id} ${
          result.scenario.name
        } completed with score: ${score(result)}`
      );
    }
  }
}

// Attempt to run a scenario using the reference (golden) patch
// Replace the golden patch with Agent logic or other custom logic to evaluate the scenario
// Returns a ScenarioRunResult with the scenario, run result, and any error
async function attemptScenarioRunWithGoldenPatch(
  runloop: Runloop,
  scenarioId: string,
  benchmarkRunId?: string,
  keepDevbox: boolean = false
): Promise<ScenarioRunResult> {
  try {
    // Retrieve scenario details from the API
    const scenario = await runloop.scenarios.retrieve(scenarioId);
    // Actually run the scenario (see below)
    const run = await runScenarioWithReferenceSolution(
      runloop,
      scenario,
      benchmarkRunId,
      keepDevbox
    );
    return { scenario, run };
  } catch (e: any) {
    // If anything fails, return the error and a minimal scenario object
    return {
      scenario: {
        id: scenarioId,
        name: "",
        input_context: { problem_statement: "" },
        metadata: {},
        scoring_contract: { scoring_function_parameters: [] },
      },
      error: e.message || String(e),
    };
  }
}

// Actually run a scenario using the reference patch, score it, and clean up
// This function mirrors the core logic of the Python example
async function runScenarioWithReferenceSolution(
  runloop: Runloop,
  scenario: ScenarioView,
  benchmarkRunId?: string,
  keepDevbox: boolean = false
): Promise<ScenarioRunView> {
  console.log(`Running scenario: ${scenario.id} ${scenario.name}`);
  console.log(
    `View Scenario Info at: https://platform.runloop.ai/scenarios/${scenario.id}`
  );

  // Step 1. Start a scenario run and wait for the devbox environment to be ready
  // This creates a new devbox and prepares it for testing
  const scenarioRun = await runloop.scenarios.startRunAndAwaitEnvReady({
    scenario_id: scenario.id,
    benchmark_run_id: benchmarkRunId,
  });
  console.log(
    `View Run Results at: https://platform.runloop.ai/scenarios/${scenario.id}/runs/${scenarioRun.id}`
  );

  // Step 2. Apply the reference solution (golden patch) to the devbox
  // This writes the patch file and applies it using the 'patch' command
  // TODO: Replace this solution with Agent logic or other custom logic to realistically evaluate the scenario
  await runloop.devboxes.writeFileContents(scenarioRun.devbox_id, {
    file_path: "/home/user/ref.patch",
    contents: scenario.reference_output || "",
  });
  await runloop.devboxes.executeSync(scenarioRun.devbox_id, {
    command: "cd /testbed && patch -p1 < /home/user/ref.patch",
  });

  // Step 3. Score the scenario using the Runloop scoring contract
  // This will run all configured scorers and return the result
  const result = await runloop.scenarios.runs.scoreAndAwait(scenarioRun.id);
  const score = result.scoring_contract_result?.score;
  console.log(`Scoring result: id=${result.id} score=${score}`);

  // Step 4. Optionally complete (delete) the devbox to clean up resources
  if (!keepDevbox) {
    await runloop.scenarios.runs.complete(scenarioRun.id);
  } else {
    console.log(
      `Keeping devbox ${scenarioRun.devbox_id} running for manual inspection`
    );
  }
  return result;
}

// Start the CLI tool
main().catch((err) => {
  console.error(err);
  process.exit(1);
});
