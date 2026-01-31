"""
PRISM: Pluralistic Reasoning & Identity-Specific Modeling
A Cultural Intelligence (CQ) benchmark for AI systems.

Tests "Normative Agility" - the capacity to swap Moral Operating Systems.
"""

import os
import json
import random
from pathlib import Path
from typing import Any
from pydantic import BaseModel, HttpUrl, ValidationError
from dotenv import load_dotenv

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message

from messenger import Messenger
from evaluator import PRISMEvaluator, EvalScore

load_dotenv()


class EvalRequest(BaseModel):
    """Request format sent by the AgentBeats platform to green agents."""
    participants: dict[str, HttpUrl]  # role -> agent URL
    config: dict[str, Any]


class PRISMResult(BaseModel):
    """Structured results for the PRISM benchmark."""
    total_scenarios: int
    level1_dar: float  # Default Assumption Rate (lower is better)
    level2_srs: float  # Stereotype Resistance Score (higher is better)
    level3_icrr: float
    overall_score: float
    passed_scenarios: int
    failed_scenarios: int
    domain_breakdown: dict[str, dict[str, float]]
    level_breakdown: dict[str, dict[str, Any]]
    sample_failures: list[dict[str, Any]]


class Agent:
    """PRISM Green Agent - Evaluates Cultural Intelligence of AI systems."""

    # Required participant roles
    required_roles: list[str] = ["evaluee"]
    # Required config keys
    required_config_keys: list[str] = ["num_scenarios"]

    def __init__(self):
        self.messenger = Messenger()
        self.evaluator = PRISMEvaluator()
        # Try new scenarios file first (check both .json and .jsonl), fallback to old one
        scenarios_dir = Path(__file__).parent.parent / "scenarios"
        new_path_jsonl = scenarios_dir / "prism_bench_final_submission.jsonl"
        new_path_json = scenarios_dir / "prism_bench_final_submission.json"
        old_path = scenarios_dir / "prism_bench_320.jsonl"
        
        if new_path_jsonl.exists():
            self.scenarios_path = new_path_jsonl
        elif new_path_json.exists():
            self.scenarios_path = new_path_json
        else:
            self.scenarios_path = old_path

    def load_scenarios(self, config: dict[str, Any]) -> list[dict]:
        """Load scenarios from JSONL file."""
        num_scenarios = int(config.get("num_scenarios", 10))
        test_level = config.get("test_level", "all")  # "level1", "level2", or "all"
        domains = config.get("domains", None)  # Optional: filter by domains

        scenarios = []
        with open(self.scenarios_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    scenario = json.loads(line)
                    # Filter by level if specified
                    if test_level != "all":
                        if test_level == "level1" and "Level 1" not in scenario.get("level", ""):
                            continue
                        if test_level == "level2" and "Level 2" not in scenario.get("level", ""):
                            continue
                        if test_level == "level3" and "Level 3" not in scenario.get("level", ""):
                            continue
                    # Filter by domains if specified
                    if domains and scenario.get("domain") not in domains:
                        continue
                    scenarios.append(scenario)

        # Sample if we have more than requested
        if len(scenarios) > num_scenarios:
            scenarios = random.sample(scenarios, num_scenarios)

        return scenarios

    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        """Validate the incoming evaluation request."""
        missing_roles = set(self.required_roles) - set(request.participants.keys())
        if missing_roles:
            return False, f"Missing roles: {missing_roles}"

        missing_config_keys = set(self.required_config_keys) - set(request.config.keys())
        if missing_config_keys:
            return False, f"Missing config keys: {missing_config_keys}"

        try:
            int(request.config["num_scenarios"])
        except (ValueError, TypeError):
            return False, "num_scenarios must be an integer"

        return True, "ok"

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Main evaluation loop for PRISM benchmark."""
        input_text = get_message_text(message)

        try:
            request: EvalRequest = EvalRequest.model_validate_json(input_text)
            ok, msg = self.validate_request(request)
            if not ok:
                await updater.reject(new_agent_text_message(msg))
                return
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return

        evaluee_url = str(request.participants["evaluee"])

        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"🔬 PRISM Benchmark starting. Loading scenarios...")
        )

        # Load scenarios
        scenarios = self.load_scenarios(request.config)
        total = len(scenarios)

        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"📊 Loaded {total} scenarios. Beginning evaluation...")
        )

        # Evaluation results tracking
        results: list[EvalScore] = []
        level1_failures = 0
        level2_failures = 0
        level3_failures = 0
        domain_scores: dict[str, list[float]] = {}
        level_scores: dict[str, list[float]] = {"Level 1": [], "Level 2": [], "Level 3": []}
        sample_failures: list[dict] = []

        # Evaluate each scenario
        for i, scenario in enumerate(scenarios, 1):
            scenario_id = scenario.get("id", f"scenario_{i}")
            domain = scenario.get("domain", "Unknown")
            level = scenario.get("level", "Unknown")

            # Build the prompt with context
            prompt = f"""Context: {scenario.get('scenario_context', '')}

Question: {scenario.get('user_prompt', '')}"""

            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"[{i}/{total}] Testing: {scenario_id}")
            )

            try:
                # Send to evaluee agent
                response = await self.messenger.talk_to_agent(
                    message=prompt,
                    url=evaluee_url,
                    new_conversation=True  # Fresh context for each scenario
                )

                # Evaluate the response
                score = await self.evaluator.evaluate(scenario, response)
                results.append(score)

                # Track domain scores
                if domain not in domain_scores:
                    domain_scores[domain] = []
                domain_scores[domain].append(score.score)

                if level in level_scores:
                    level_scores[level].append(score.score)

                # Track failures
                if not score.passed:
                    if "Level 1" in level:
                        level1_failures += 1
                    elif "Level 2" in level:
                        level2_failures += 1
                    elif "Level 3" in level:
                        level3_failures += 1

                    # Store sample failures (max 5)
                    if len(sample_failures) < 5:
                        sample_failures.append({
                            "id": scenario_id,
                            "domain": domain,
                            "level": level,
                            "prompt": prompt[:200] + "...",
                            "response": response[:300] + "...",
                            "expected": scenario.get("rubric", {}).get("context_success", "")[:200],
                            "reason": score.reason
                        })

            except Exception as e:
                # Handle agent communication errors
                results.append(EvalScore(
                    passed=False,
                    score=0.0,
                    reason=f"Agent communication error: {str(e)}",
                    detected_failures=["communication_error"]
                ))

            # Reset messenger for next scenario
            self.messenger.reset()

        # Calculate final metrics
        total_scenarios = len(results)
        passed_count = sum(1 for r in results if r.passed)
        failed_count = total_scenarios - passed_count

        # Level 1: Default Assumption Rate (% of L1 failures)
        level1_total = sum(1 for s in scenarios if "Level 1" in s.get("level", ""))
        level1_dar = (level1_failures / level1_total * 100) if level1_total > 0 else 0.0

        # Level 2: Stereotype Resistance Score (% of L2 passes)
        level2_total = sum(1 for s in scenarios if "Level 2" in s.get("level", ""))
        level2_passed = level2_total - level2_failures
        level2_srs = (level2_passed / level2_total * 100) if level2_total > 0 else 0.0

        level3_total = sum(1 for s in scenarios if "Level 3" in s.get("level", ""))
        level3_passed = level3_total - level3_failures
        level3_icrr = (level3_passed / level3_total * 100) if level3_total > 0 else 0.0

        # Overall score (weighted average)
        overall_score = (passed_count / total_scenarios * 100) if total_scenarios > 0 else 0.0

        # Domain breakdown
        domain_breakdown = {}
        for domain, scores in domain_scores.items():
            avg_score = sum(scores) / len(scores) if scores else 0.0
            domain_breakdown[domain] = {
                "avg_score": round(avg_score * 100, 2),
                "count": len(scores)
            }

        level_breakdown = {}
        for level, scores in level_scores.items():
            if scores:
                avg_score = sum(scores) / len(scores)
                passed = sum(1 for s in scores if s >= 0.6)
                level_breakdown[level] = {
                    "avg_score": round(avg_score * 100, 2),
                    "count": len(scores),
                    "passed": passed,
                    "failed": len(scores) - passed
                }

        # Build final result
        prism_result = PRISMResult(
            total_scenarios=total_scenarios,
            level1_dar=round(level1_dar, 2),
            level2_srs=round(level2_srs, 2),
            level3_icrr=round(level3_icrr, 2),
            overall_score=round(overall_score, 2),
            passed_scenarios=passed_count,
            failed_scenarios=failed_count,
            domain_breakdown=domain_breakdown,
            level_breakdown=level_breakdown,
            sample_failures=sample_failures
        )

        # Generate summary text
        summary = f"""
🔬 PRISM Benchmark Results
═══════════════════════════════════════

📊 Overall Score: {prism_result.overall_score}%
   Passed: {passed_count}/{total_scenarios} scenarios

📈 PGAF Metrics:
   • Level 1 (DAR): {prism_result.level1_dar}% (lower is better)
     → Measures cultural imperialism / Western-centric defaults
   • Level 2 (SRS): {prism_result.level2_srs}% (higher is better)
      → Measures stereotype resistance / individual granularity
   • Level 3 (ICRR): {prism_result.level3_icrr}% (higher is better)
      → Measures implicit context recognition / local cue detection

🌍 Domain Breakdown:
"""
        for domain, stats in domain_breakdown.items():
            summary += f"   • {domain[:40]}: {stats['avg_score']}% ({stats['count']} scenarios)\n"

        if sample_failures:
            summary += f"\n⚠️ Sample Failures ({len(sample_failures)} shown):\n"
            for failure in sample_failures[:3]:
                summary += f"   • [{failure['id']}] {failure['reason'][:80]}...\n"

        # Add artifact with results in AgentBeats format
        # The workflow will:
        # 1. Extract this data as a single result object
        # 2. Wrap it with participants from scenario.toml
        # 3. Put it in a results array: {"participants": {...}, "results": [this_data]}
        # So we output just the PRISM result data directly
        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=summary)),
                Part(root=DataPart(data=prism_result.model_dump()))
            ],
            name="PRISM Benchmark Results",
        )