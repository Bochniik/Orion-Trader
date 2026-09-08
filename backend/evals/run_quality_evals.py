import json
from pathlib import Path


CASES_PATH = Path(__file__).with_name("quality_cases.json")


def load_cases(path=CASES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_answer(answer, case):
    normalized = answer.lower()
    required = [term.lower() for term in case.get("required_any", [])]
    forbidden = [term.lower() for term in case.get("forbidden", [])]
    return {
        "name": case["name"],
        "mentions_required_concept": not required or any(term in normalized for term in required),
        "avoids_forbidden_claims": not any(term in normalized for term in forbidden),
        "nonempty": bool(answer.strip()),
    }


def run_fixture_evals(path=CASES_PATH):
    results = [evaluate_answer(case["fixture_answer"], case) for case in load_cases(path)]
    return results, all(all(value for key, value in result.items() if key != "name") for result in results)


if __name__ == "__main__":
    evaluation_results, passed = run_fixture_evals()
    print(json.dumps({"passed": passed, "results": evaluation_results}, indent=2))
    raise SystemExit(0 if passed else 1)
