from runloop_api_client import AsyncRunloop
import os
import asyncio
from runloop_api_client.types import (
    ScoringContractParam,
    ScenarioEnvironment,
    InputContextParam,
    LaunchParameters,
)
from typing import List, TypedDict, Dict, Optional


class ScenarioConfig(TypedDict):
    name: str
    input_context: Optional[InputContextParam]
    scoring_contract: Optional[ScoringContractParam]
    environment_parameters: Optional[ScenarioEnvironment]
    metadata: Dict[str, str] | {
        "custom_scenario": "True",
    }
    reference_output: Optional[str]


client = AsyncRunloop(
    bearer_token=os.getenv("RUNLOOP_API_KEY"),
)


# Wrapper for creating a custom scenario
async def create_custom_scenario(client: AsyncRunloop, scenario_config: ScenarioConfig):
    scenario = await client.scenarios.create(
        **scenario_config,
        is_public=False,
    )
    return scenario


# Toy example of creating a custom scorer
# Custom scorers are great tools when scoring logic is a script that can be re-used across multiple scenarios
# In this case, this custom scorer always returns 1.0
async def create_toy_custom_scorer(client: AsyncRunloop):
    new_scorer = await client.scenarios.scorers.create(
        name="aider-custom-scorer",
        code="""
        echo "1.0"
        """,
    )
    return new_scorer


async def create_custom_scenarios_and_benchmark():
    print("[INFO] Starting custom scenario and benchmark creation process...")
    # Step 1: Make a demo devbox environment with aider installed and make a snapshot of it to use as a scenario harness.
    print("[INFO] Creating aider-enabled devbox environment...")
    aider_devbox = await client.devboxes.create_and_await_running(
        name="aider-enabled Devbox",
        launch_parameters=LaunchParameters(
            launch_commands=[
                "sudo apt-get update && sudo apt-get install  -y libsqlite3-dev",
                "wget -qO- https://aider.chat/install.sh | sh",
                "echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc",
                "git init .",
            ],
        ),
        environment_variables={
            "SERVICE_API_KEY": os.getenv("SERVICE_API_KEY"),
        },
        metadata={"is_template_devbox": "true"},
    )
    print(f"[INFO] Devbox created with ID: {aider_devbox.id}")
    print("[INFO] (Snapshot and shutdown steps are mocked in this script)")

    aider_snapshot = await client.devboxes.snapshot_disk(
        id=aider_devbox.id,
        name="aider-devbox-custom-scenario-harness",
        timeout=300,
    )
    print(f"[INFO] Snapshot created with ID: {aider_snapshot.id}")
    await client.devboxes.shutdown(id=aider_devbox.id)
    print(f"[INFO] Devbox with ID {aider_devbox.id} has been shut down.")

    # Step 2: Construct a set of scenarios
    # Scenarios can be constructed with Snapshot ID, a Blueprint ID, or other launch parameters
    # If none are specified, a default devbox will be used
    print("[INFO] Constructing scenario configurations...")
    scenario_inputs: List[ScenarioConfig] = [
        # Scenario with bash scorer
        ScenarioConfig(
            name="aider-custom-scenario-bash",
            input_context=InputContextParam(
                problem_statement="aider can write the index.py file that prints 'Hello' to the console",
                additional_context=None,
            ),
            scoring_contract=ScoringContractParam(
                scoring_function_parameters=[
                    {
                        "name": "script_output_is_hello",
                        "scorer": {
                            "type": "bash_script_scorer",
                            "bash_script": '#!/bin/bash\n\noutput=$(python index.py)\n\nif [ "$output" == "Hello" ]; then\n  echo "1.0"\n  exit 1\nelse\n  echo "0.0"\n  exit 1\nfi',
                        },
                        "weight": 1.0,
                    }
                ]
            ),
            environment_parameters=ScenarioEnvironment(
                snapshot_id=aider_snapshot.id,
            ),
            metadata={
                "description": "aider can write the index.py file that prints 'Hello' to the console",
            },
        ),
        # Scenario with ast-grep scorer
        ScenarioConfig(
            name="aider-custom-scenario-ast-grep",
            input_context=InputContextParam(
                problem_statement="aider can write the index.py file that prints 'Hello' to the console",
                additional_context=None,
            ),
            scoring_contract=ScoringContractParam(
                scoring_function_parameters=[
                    {
                        "name": "script_output_is_hello",
                        "scorer": {
                            "type": "ast_grep_scorer",
                            "pattern": 'print("Hello")',
                            "search_directory": ".",
                            "lang": "python",
                        },
                        "weight": 1.0,
                    }
                ]
            ),
            environment_parameters=ScenarioEnvironment(
                snapshot_id=aider_snapshot.id,
            ),
            metadata={
                "description": "aider can write the index.py file that prints 'Hello' to the console",
            },
        ),
        # Scenario with command, python, and test scorer
        ScenarioConfig(
            name="aider-custom-scenario-command-python-test",
            input_context=InputContextParam(
                problem_statement="aider can write the index.py file that prints 'Hello' to the console",
                additional_context=None,
            ),
            scoring_contract=ScoringContractParam(
                scoring_function_parameters=[
                    {
                        "name": "script_output_is_hello",
                        "scorer": {
                            "type": "command_scorer",
                            "command": "echo '1.0'",
                        },
                        "weight": 0.3,
                    },
                    {
                        "name": "script_output_is_hello",
                        "scorer": {
                            "type": "python_script_scorer",
                            "python_script": 'print("1.0")',
                            "requirements_contents": "\n",
                        },
                        "weight": 0.3,
                    },
                    {
                        "name": "script_output_is_hello",
                        "scorer": {
                            "type": "test_based_scorer",
                            "test_command": "python test_index.py",
                            "test_files": [
                                {
                                    "file_contents": 'print("1.0")',
                                    "file_path": "/test_index.py",
                                }
                            ],
                        },
                        "weight": 0.4,
                    },
                ]
            ),
            environment_parameters=ScenarioEnvironment(
                snapshot_id=aider_snapshot.id,
            ),
            metadata={
                "description": "aider can write the index.py file that prints 'Hello' to the console",
            },
        ),
        # Scenario with custom scorer, commented out to avoid redundancy
        #
        # custom_scorer = await create_toy_custom_scorer(client)
        # ScenarioConfig(
        #     name="aider-custom-scenario-custom-scorer",
        #     input_context=InputContextParam(
        #         problem_statement="aider can write the index.py file that prints 'Hello' to the console",
        #         additional_context=None,
        #     ),
        #     scoring_contract=ScoringContractParam(
        #         scoring_function_parameters=[
        #             {
        #                 "name": "script_output_is_hello",
        #                 "scorer": {
        #                     "type": "custom_scorer",
        #                     "custom_scorer_type": custom_scorer.type,  # Name, labelled as Type by Runloop, of the custom scorer
        #                     "scorer_params": {},
        #                 },
        #                 "weight": 1.0,
        #             }
        #         ]
        #     ),
        # ),
    ]

    print(f"[INFO] Creating {len(scenario_inputs)} scenarios...")
    scenario_ids = []
    for idx, scenario in enumerate(scenario_inputs):
        print(
            f"[INFO] Creating scenario {idx+1}/{len(scenario_inputs)}: {scenario['name']}"
        )
        created_scenario = await create_custom_scenario(client, scenario)
        print(f"[INFO] Scenario created with ID: {created_scenario.id}")
        scenario_ids.append(created_scenario.id)

    print("[INFO] All scenarios created. Creating benchmark...")
    custom_benchmark = await client.benchmarks.create(
        # Benchmark names are unique
        name="Aider Custom Scenario Benchmark",
        scenario_ids=scenario_ids,
        is_public=False,
    )
    print(f"[INFO] Benchmark created with ID: {custom_benchmark.id}")
    print("[INFO] Custom benchmark creation process completed.")

    # After the benchmark is created, you can use the harness in run_public_benchmark.py to run the benchmark and evaluate the results in the same way as public benchmarks.


if __name__ == "__main__":
    asyncio.run(create_custom_scenarios_and_benchmark())
