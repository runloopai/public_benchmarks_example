"""Create a subset of a benchmark with desired properties."""

import asyncio
from runloop_api_client import NOT_GIVEN, AsyncRunloop, NotGiven
from runloop_api_client.types import ScenarioView

runloop_api = AsyncRunloop()

benchmark_id = "bmd_3056xc0UoFk0xSyRKtfqC"
# Set to the name of the benchmark you will clone into
cloned_name = "scoped-fast-sample"


async def list_all_scenarios(search_string: str) -> list[ScenarioView]:
    scenarios: list[ScenarioView] = []
    starting_after: str | NotGiven = NOT_GIVEN
    while True:
        scenarios_response = await runloop_api.scenarios.list_public(
            extra_query={"search": f"{search_string}"},
            limit=100,
            starting_after=starting_after,
        )
        scenarios.extend(scenarios_response.scenarios)
        if not scenarios_response.has_more:
            break

        starting_after = scenarios_response.scenarios[-1].id

    return scenarios


async def main():
    benchmark = await runloop_api.benchmarks.retrieve(benchmark_id)

    # Example search queries gather a set of scenarios that score relatively fast (less than 60 seconds)
    search_queries = [
        "lincolnloop__python-qrcode",
        "jd__tenacity",
        "jaraco__inflect",
        "pwaller__pyfiglet",
        "john-kurkowski__tldextract",
        "agronholm__exceptiongroup",
        "theskumar__python-dotenv",
        "aio-libs__async-timeout",
        "agronholm__exceptiongroup",
    ]

    benchmark_scenario_ids = set([id for id in benchmark.scenario_ids])

    scoped_scenarios: list[ScenarioView] = []
    for search_query in search_queries:
        query_scenarios = await list_all_scenarios(search_query)

        print(f"found {len(query_scenarios)} scenarios matching search: {search_query}")
        scoped_scenarios.extend(query_scenarios)

    # Filter scenarios to only include those whose IDs are in benchmark_scenario_ids set
    final_scenarios = [
        scenario
        for scenario in scoped_scenarios
        if scenario.id in benchmark_scenario_ids
    ]

    print(f"benchmark contains {len(benchmark_scenario_ids)} scenarios")
    print(
        f"matched {len(final_scenarios)} scenarios out of {len(scoped_scenarios)} total scenarios"
    )

    response = input("create new benchmark? (y/n)")
    if response == "y":
        name = f"{cloned_name} - {benchmark.name}"

        existing_benchmarks = await runloop_api.benchmarks.list(
            extra_query={"search": f"{cloned_name}"}
        )
        if existing_benchmarks.benchmarks:
            print(f"existing benchmark found: {existing_benchmarks.benchmarks[0].id}")
            # update
            await runloop_api.benchmarks.update(
                id=existing_benchmarks.benchmarks[0].id,
                name=name,
                scenario_ids=[scenario.id for scenario in final_scenarios],
            )
            print(f"benchmark updated: {existing_benchmarks.benchmarks[0].id}")
            return
        else:
            print(f"creating new benchmark: {name}")

            new_benchmark = await runloop_api.benchmarks.create(
                name=name,
                scenario_ids=[scenario.id for scenario in final_scenarios],
            )
            print(f"new benchmark created: {new_benchmark.id}")


if __name__ == "__main__":
    asyncio.run(main())
