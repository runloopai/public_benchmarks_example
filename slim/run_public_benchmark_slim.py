#!/usr/bin/env python3
"""
Slim version of run_public_benchmark.py without runloop-api-client dependency.
Uses direct HTTP calls with asyncio.
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class Scenario:
    """Represents a benchmark scenario."""
    id: str
    name: str
    input_context: dict
    metadata: dict
    reference_output: Optional[str]


@dataclass
class ScenarioRun:
    """Represents a running instance of a scenario."""
    id: str
    scenario_id: str
    devbox_id: str
    state: str  # "pending", "running", "scoring", "scored", "completed"
    status: Optional[str] = None  # For backward compatibility
    scoring_contract_result: Optional[dict] = None


@dataclass
class Devbox:
    """Represents a development environment."""
    id: str
    status: str


class RunloopClient:
    """Client for interacting with the Runloop API using direct HTTP calls."""

    def __init__(self, api_base_url: str = "https://api.runloop.ai/v1", api_key: Optional[str] = None):
        """
        Initialize the Runloop API client.

        Args:
            api_base_url: Base URL for the API (default: https://api.runloop.ai/v1)
            api_key: API key for authentication (default: from RUNLOOP_API_KEY env var)
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("RUNLOOP_API_KEY")

        if not self.api_key:
            raise ValueError("API key must be provided or set in RUNLOOP_API_KEY environment variable")

        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        Make a GET request to the API.

        Args:
            path: API endpoint path
            params: Optional query parameters

        Returns:
            Response data as dictionary
        """
        url = f"{self.api_base_url}{path}"
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Request error: {str(e)}")

    async def _post(self, path: str, json: Optional[dict] = None) -> dict:
        """
        Make a POST request to the API.

        Args:
            path: API endpoint path
            json: Optional JSON body

        Returns:
            Response data as dictionary
        """
        url = f"{self.api_base_url}{path}"
        try:
            response = await self.client.post(url, json=json or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Request error: {str(e)}")

    async def _put(self, path: str, json: Optional[dict] = None) -> dict:
        """
        Make a PUT request to the API.

        Args:
            path: API endpoint path
            json: Optional JSON body

        Returns:
            Response data as dictionary
        """
        url = f"{self.api_base_url}{path}"
        try:
            response = await self.client.put(url, json=json or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Request error: {str(e)}")

    def _parse_scenario(self, data: dict) -> Scenario:
        """Parse API response into Scenario object."""
        return Scenario(
            id=data["id"],
            name=data["name"],
            input_context=data.get("input_context", {}),
            metadata=data.get("metadata", {}),
            reference_output=data.get("reference_output")
        )

    def _parse_scenario_run(self, data: dict) -> ScenarioRun:
        """Parse API response into ScenarioRun object."""
        return ScenarioRun(
            id=data["id"],
            scenario_id=data["scenario_id"],
            devbox_id=data["devbox_id"],
            state=data.get("state", "pending"),
            status=data.get("status"),
            scoring_contract_result=data.get("scoring_contract_result")
        )

    def _parse_devbox(self, data: dict) -> Devbox:
        """Parse API response into Devbox object."""
        return Devbox(
            id=data["id"],
            status=data["status"]
        )

    async def get_scenario(self, scenario_id: str) -> Scenario:
        """
        Get scenario details by ID.

        Args:
            scenario_id: ID of the scenario to retrieve

        Returns:
            Scenario object
        """
        data = await self._get(f"/scenarios/{scenario_id}")
        return self._parse_scenario(data)

    async def start_scenario_run(self, scenario_id: str) -> ScenarioRun:
        """
        Start a new scenario run.

        Args:
            scenario_id: ID of the scenario to run

        Returns:
            ScenarioRun object
        """
        data = await self._post("/scenarios/start_run", json={"scenario_id": scenario_id})
        return self._parse_scenario_run(data)

    async def get_scenario_run(self, run_id: str) -> ScenarioRun:
        """
        Get scenario run details by ID.

        Args:
            run_id: ID of the scenario run

        Returns:
            ScenarioRun object
        """
        data = await self._get(f"/scenarios/runs/{run_id}")
        return self._parse_scenario_run(data)

    async def score_scenario_run(self, run_id: str) -> ScenarioRun:
        """
        Trigger scoring for a scenario run.

        Args:
            run_id: ID of the scenario run

        Returns:
            ScenarioRun object with scoring results
        """
        data = await self._post(f"/scenarios/runs/{run_id}/score")
        return self._parse_scenario_run(data)

    async def complete_scenario_run(self, run_id: str) -> None:
        """
        Mark a scenario run as complete.

        Args:
            run_id: ID of the scenario run
        """
        await self._post(f"/scenarios/runs/{run_id}/complete")

    async def write_devbox_file(self, devbox_id: str, file_path: str, contents: str) -> None:
        """
        Write a file to the devbox.

        Args:
            devbox_id: ID of the devbox
            file_path: Path where the file should be written
            contents: File contents
        """
        await self._post(
            f"/devboxes/{devbox_id}/write_file_contents",
            json={"file_path": file_path, "contents": contents}
        )

    async def read_devbox_file(self, devbox_id: str, file_path: str) -> str:
        """
        Read a file from the devbox.

        Args:
            devbox_id: ID of the devbox
            file_path: Path of the file to read

        Returns:
            File contents as string
        """
        # Note: The API returns text/plain, not JSON
        url = f"{self.api_base_url}/devboxes/{devbox_id}/read_file_contents"
        try:
            response = await self.client.post(url, json={"file_path": file_path})
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"Request error: {str(e)}")

    async def execute_async(self, devbox_id: str, command: str) -> dict:
        """
        Execute a command asynchronously in the devbox.

        Args:
            devbox_id: ID of the devbox
            command: Command to execute

        Returns:
            Execution metadata dictionary
        """
        return await self._post(
            f"/devboxes/{devbox_id}/execute_async",
            json={"command": command}
        )

    async def get_devbox(self, devbox_id: str) -> Devbox:
        """
        Get devbox details by ID.

        Args:
            devbox_id: ID of the devbox

        Returns:
            Devbox object
        """
        data = await self._get(f"/devboxes/{devbox_id}")
        return self._parse_devbox(data)

    async def get_execution(self, devbox_id: str, execution_id: str) -> dict:
        """
        Get execution details.

        Args:
            devbox_id: ID of the devbox
            execution_id: ID of the execution

        Returns:
            Execution details dictionary
        """
        return await self._get(f"/devboxes/{devbox_id}/executions/{execution_id}")

    async def wait_for_devbox_running(
        self,
        devbox_id: str,
        timeout_seconds: int = 120
    ) -> Devbox:
        """
        Poll until devbox is in running state.

        Args:
            devbox_id: ID of the devbox
            timeout_seconds: Maximum time to wait in seconds (default: 120)

        Returns:
            Devbox object when running

        Raises:
            Exception: If timeout exceeded
        """
        print(f"Waiting for devbox {devbox_id} to be running...")
        interval = 2
        max_attempts = timeout_seconds // interval

        for attempt in range(max_attempts):
            devbox = await self.get_devbox(devbox_id)
            if devbox.status == "running":
                print(f"Devbox is now running")
                return devbox
            await asyncio.sleep(interval)

        raise Exception(f"Devbox not running after {timeout_seconds} seconds")

    async def execute_async_and_wait(
        self,
        devbox_id: str,
        command: str,
        timeout_seconds: int = 1800
    ) -> dict:
        """
        Execute a command asynchronously and wait for completion.

        Args:
            devbox_id: ID of the devbox
            command: Command to execute
            timeout_seconds: Maximum time to wait in seconds (default: 1800 = 30 minutes)

        Returns:
            Execution result dictionary

        Raises:
            Exception: If timeout exceeded or execution failed
        """
        print(f"Executing async command: {command}")
        exec_result = await self.execute_async(devbox_id, command)
        execution_id = exec_result.get("execution_id")

        if not execution_id:
            raise Exception(f"No execution ID returned from execute_async. Response: {exec_result}")

        print(f"Execution started with ID: {execution_id}")

        interval = 5
        max_attempts = timeout_seconds // interval

        for attempt in range(max_attempts):
            execution = await self.get_execution(devbox_id, execution_id)
            status = execution.get("status")

            if status == "completed":
                print(f"Execution completed")
                return execution

            await asyncio.sleep(interval)

        raise Exception(f"Execution did not complete after {timeout_seconds} seconds")

    async def wait_for_devbox_ready(
        self,
        run_id: str,
        max_attempts: int = 120,
        interval: int = 5
    ) -> ScenarioRun:
        """
        Poll until devbox is ready.

        Args:
            run_id: ID of the scenario run
            max_attempts: Maximum number of polling attempts
            interval: Seconds between polling attempts

        Returns:
            ScenarioRun object when devbox is ready

        Raises:
            Exception: If max_attempts exceeded
        """
        print("Waiting for devbox to be ready...")
        for attempt in range(max_attempts):
            run = await self.get_scenario_run(run_id)
            if run.state == "running":
                print(f"Devbox ready: {run.devbox_id}")
                return run
            await asyncio.sleep(interval)

        raise Exception(f"Devbox not ready after {max_attempts * interval} seconds")

    async def wait_for_scoring_complete(
        self,
        run_id: str,
        max_attempts: int = 360,
        interval: int = 5
    ) -> ScenarioRun:
        """
        Poll until scoring is complete.

        Args:
            run_id: ID of the scenario run
            max_attempts: Maximum number of polling attempts
            interval: Seconds between polling attempts

        Returns:
            ScenarioRun object with scoring results

        Raises:
            Exception: If max_attempts exceeded
        """
        print("Waiting for scoring...")
        # First, trigger scoring
        await self.score_scenario_run(run_id)

        # Then poll until scoring is complete
        for attempt in range(max_attempts):
            run = await self.get_scenario_run(run_id)
            if run.state == "scored":
                print("Scoring complete!")
                return run
            await asyncio.sleep(interval)

        raise Exception(f"Scoring not complete after {max_attempts * interval} seconds")


async def run_scenario_workflow(client: RunloopClient, scenario_id: str) -> float:
    """
    Execute the complete scenario workflow.

    Args:
        client: RunloopClient instance
        scenario_id: ID of the scenario to run

    Returns:
        Final score
    """
    # 1. Retrieve scenario
    print(f"Starting scenario run for: {scenario_id}")
    scenario = await client.get_scenario(scenario_id)
    print(f"Scenario: {scenario.name}")

    # 2. Start scenario run
    run = await client.start_scenario_run(scenario_id)
    print(f"Started run: {run.id}")

    # 3. Wait for scenario run devbox to be ready
    run = await client.wait_for_devbox_ready(run.id)

    # 4. Wait for devbox to be in running state
    await client.wait_for_devbox_running(run.devbox_id, timeout_seconds=120)

    # 5. Write tmp.txt
    print("Writing tmp.txt...")
    await client.write_devbox_file(run.devbox_id, "/home/user/tmp.txt", "hello slim client!")

    # 6. Read tmp.txt
    content = await client.read_devbox_file(run.devbox_id, "/home/user/tmp.txt")
    print(f"Read from tmp.txt: {content}")

    # 7. Execute async command and wait for completion
    exec_result = await client.execute_async_and_wait(
        run.devbox_id,
        "sleep 10 && cat /home/user/tmp.txt",
        timeout_seconds=1800
    )

    # Print execution results
    print(f"Execution exit code: {exec_result.get('exit_status')}")
    print(f"Execution stdout: {exec_result.get('stdout', '')}")
    if exec_result.get('stderr'):
        print(f"Execution stderr: {exec_result.get('stderr')}")

    # Demo: Try to read a file that doesn't exist
    print("\n--- Reading non-existent file ---")
    try:
        await client.read_devbox_file(run.devbox_id, "/home/user/nonexistent.txt")
    except Exception as e:
        print(f"Expected error when reading non-existent file: {e}")

    # Demo: Try to execute a binary that doesn't exist
    print("\n--- Executing non-existent binary ---")
    try:
        exec_result = await client.execute_async_and_wait(
            run.devbox_id,
            "nonexistent_binary --flag",
            timeout_seconds=60
        )
        print(f"Exit status: {exec_result.get('exit_status')}")
        print(f"Stderr: {exec_result.get('stderr', '')}")
    except Exception as e:
        print(f"Error during execution: {e}")

    # 8. Score scenario
    run = await client.wait_for_scoring_complete(run.id)

    # 9. Complete scenario
    await client.complete_scenario_run(run.id)

    # 10. Extract and return score
    score = run.scoring_contract_result.get("score", 0.0)
    return score


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run a single scenario with slim client")
    parser.add_argument("--scenario-id", type=str, required=True, help="Scenario ID to run")
    args = parser.parse_args()

    client = RunloopClient()
    try:
        score = await run_scenario_workflow(client, args.scenario_id)
        print(f"Final score: {score}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
