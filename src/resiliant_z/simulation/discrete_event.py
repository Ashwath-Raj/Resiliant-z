"""CPU-only discrete-event fleet model for local development.

This is a simplified queueing model—not Isaac Sim, a physics simulator, or a
validated warehouse digital twin. Unlike the algebraic test surrogate, congestion
emerges from finite robot availability and shared route servers. Assumptions are
explicit so the model is useful for workflow development without being mistaken
for physical evidence.
"""

from __future__ import annotations

import heapq
import random
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from resiliant_z.models import ExperimentManifest, ScenarioMetrics, SimulationRun
from resiliant_z.scenario import (
    HIGH_DEMAND_THRESHOLD,
    HIGH_PRIORITY_THRESHOLD,
    JUNCTION_PRESSURE_TRIGGER,
)


@dataclass(slots=True)
class _Task:
    task_id: int
    arrival_time: float
    is_priority: bool
    route: Literal["junction", "bypass"]
    route_uniform: float
    approach_seconds: float
    junction_service_seconds: float
    bypass_service_seconds: float
    return_seconds: float


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip() or "uncommitted"
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"


class DiscreteEventFleetSimulator:
    """Simulate a ten-robot fleet with shared junction/bypass service queues.

    Scenario assumptions:
    - ``traffic_demand`` is a workload multiplier, not a measured real-world rate.
    - Arrivals are Poisson with rate ``0.20 * traffic_demand`` tasks/second.
    - Ten robots serve jobs; a robot is occupied while approaching, crossing,
      and completing a task.
    - One junction server is shared by through-traffic. A separate bypass server
      receives the fraction selected by ``bypass_ratio``.
    - ``routing_policy="static"`` diverts by that ratio across all traffic.
      ``routing_policy="conditioned"`` permits diversion only when both workload
      factors are in the predeclared high-risk envelope and observed junction
      pressure reaches the configured trigger. These are benchmark rules, not
      learned real-world thresholds.
    - Priority jobs receive queue precedence but use longer service windows to
      represent special handling/clearance. This is an explicit scenario
      assumption, not a claim about every warehouse or robot fleet.
    - Geometry, collisions, kinematics, sensors, and true deadlocks are not
      modeled. ``deadlock_events`` therefore remains zero and must not be used
      as evidence of collision or deadlock safety.
    """

    name = "discrete_event"
    robot_count = 10
    duration_seconds = 900.0

    def run(self, manifest: ExperimentManifest) -> SimulationRun:
        p = manifest.parameters
        rng = random.Random(manifest.seed)
        event_heap: list[tuple[float, int, str, object]] = []
        event_sequence = 0

        def schedule(at: float, kind: str, payload: object) -> None:
            nonlocal event_sequence
            event_sequence += 1
            heapq.heappush(event_heap, (at, event_sequence, kind, payload))

        # Pre-schedule arrival and sampling events. All runs are deterministic
        # with respect to the manifest seed, apart from wall-clock provenance.
        arrival_rate = 0.20 * p.traffic_demand
        next_arrival = rng.expovariate(arrival_rate)
        next_task_id = 0
        while next_arrival <= self.duration_seconds:
            next_task_id += 1
            # Pre-sample all per-task randomness before simulating. This keeps
            # arrivals, task classes, route uniforms, and service-time draws paired
            # across policy arms with the same workload and seed (common random
            # numbers), instead of letting a policy change the RNG draw order.
            route_uniform = rng.random()
            is_priority = rng.random() < p.priority_ratio
            approach_seconds = rng.uniform(2.0, 4.0)
            junction_service_seconds = (
                rng.triangular(5.2, 8.0, 6.5)
                if is_priority
                else rng.triangular(3.2, 5.8, 4.2)
            )
            bypass_service_seconds = (
                rng.triangular(3.0, 5.1, 4.0)
                if is_priority
                else rng.triangular(1.8, 3.7, 2.7)
            )
            return_seconds = rng.uniform(3.0, 6.0)
            task = _Task(
                task_id=next_task_id,
                arrival_time=next_arrival,
                is_priority=is_priority,
                route="junction",
                route_uniform=route_uniform,
                approach_seconds=approach_seconds,
                junction_service_seconds=junction_service_seconds,
                bypass_service_seconds=bypass_service_seconds,
                return_seconds=return_seconds,
            )
            schedule(next_arrival, "arrival", task)
            next_arrival += rng.expovariate(arrival_rate)

        for tick in range(60, int(self.duration_seconds) + 1, 60):
            schedule(float(tick), "sample", None)

        robot_busy = [False] * self.robot_count
        robot_queue: list[_Task] = []
        route_queues: dict[str, list[_Task]] = {"junction": [], "bypass": []}
        route_busy = {"junction": False, "bypass": False}
        arrivals = 0
        completions = 0
        service_waits: dict[int, float] = {}
        arrived_tasks: dict[int, _Task] = {}
        backlog_samples: list[tuple[float, int]] = [(0.0, 0)]
        junction_busy_seconds = 0.0
        bypass_task_count = 0
        high_risk_context_arrival_count = 0
        conditional_policy_trigger_count = 0

        def pop_priority(queue: list[_Task]) -> _Task:
            # Higher-priority jobs are selected first; ties are FIFO by arrival.
            index = min(
                range(len(queue)),
                key=lambda i: (not queue[i].is_priority, queue[i].arrival_time, queue[i].task_id),
            )
            return queue.pop(index)

        def dispatch_robots(now: float) -> None:
            while robot_queue:
                try:
                    robot_id = robot_busy.index(False)
                except ValueError:
                    return
                task = pop_priority(robot_queue)
                robot_busy[robot_id] = True
                schedule(now + task.approach_seconds, "approach_done", (robot_id, task))

        # Map task to its robot from assignment through route completion.
        robot_id_for_task: dict[int, int] = {}

        def start_route(route: Literal["junction", "bypass"], now: float) -> None:
            if route_busy[route] or not route_queues[route]:
                return
            task = pop_priority(route_queues[route])
            route_busy[route] = True
            service_waits[task.task_id] = max(0.0, now - task.arrival_time)
            service_seconds = (
                task.junction_service_seconds if route == "junction" else task.bypass_service_seconds
            )
            if route == "junction":
                nonlocal junction_busy_seconds
                junction_busy_seconds += max(
                    0.0, min(service_seconds, self.duration_seconds - now)
                )
            robot_id = robot_id_for_task[task.task_id]
            schedule(now + service_seconds, "route_done", (route, robot_id, task))

        now = 0.0
        while event_heap:
            now, _, kind, payload = heapq.heappop(event_heap)
            if now > self.duration_seconds:
                break
            if kind == "arrival":
                task = payload
                assert isinstance(task, _Task)
                arrivals += 1
                arrived_tasks[task.task_id] = task
                high_risk_context = (
                    p.traffic_demand >= HIGH_DEMAND_THRESHOLD
                    and p.priority_ratio >= HIGH_PRIORITY_THRESHOLD
                )
                if high_risk_context:
                    high_risk_context_arrival_count += 1
                junction_pressure = len(route_queues["junction"]) + int(route_busy["junction"])
                condition_active = (
                    p.routing_policy == "conditioned"
                    and p.bypass_ratio > 0.0
                    and high_risk_context
                    and junction_pressure >= JUNCTION_PRESSURE_TRIGGER
                )
                if condition_active:
                    conditional_policy_trigger_count += 1
                use_bypass = (
                    task.route_uniform < p.bypass_ratio
                    and (p.routing_policy == "static" or condition_active)
                )
                task.route = "bypass" if use_bypass else "junction"
                if use_bypass:
                    bypass_task_count += 1
                robot_queue.append(task)
                dispatch_robots(now)
            elif kind == "approach_done":
                robot_id, task = payload  # type: ignore[misc]
                route = task.route
                robot_id_for_task[task.task_id] = robot_id
                route_queues[route].append(task)
                start_route(route, now)
            elif kind == "route_done":
                route, robot_id, task = payload  # type: ignore[misc]
                route_busy[route] = False
                # The robot remains busy through a short delivery/return phase.
                schedule(now + task.return_seconds, "robot_free", (robot_id, task))
                start_route(route, now)
            elif kind == "robot_free":
                robot_id, _task = payload  # type: ignore[misc]
                robot_busy[robot_id] = False
                completions += 1
                dispatch_robots(now)
            elif kind == "sample":
                backlog_samples.append((now, max(0, arrivals - completions)))

        elapsed_minutes = self.duration_seconds / 60.0
        outstanding = max(0, arrivals - completions)
        # Only tasks that actually reached route-service start have an observed
        # wait-to-start duration. Do not replace missing waits with the remaining
        # simulation horizon and then call the mixture an average wait; those tasks
        # are right-censored. Preserve that separate horizon-limited exposure metric
        # so reports can show both the started-task wait and censoring burden.
        route_service_started_count = len(service_waits)
        tasks_not_started_by_horizon = max(0, arrivals - route_service_started_count)
        route_service_wait_total = sum(service_waits.values())
        average_wait = (
            route_service_wait_total / route_service_started_count
            if route_service_started_count
            else 0.0
        )
        censored_wait_observations = [
            service_waits.get(task_id, max(0.0, self.duration_seconds - task.arrival_time))
            for task_id, task in arrived_tasks.items()
        ]
        censored_wait_observation = (
            sum(censored_wait_observations) / len(censored_wait_observations)
            if censored_wait_observations
            else 0.0
        )

        # Estimate end-window backlog growth with an OLS slope over sampled points
        # in the final five minutes. Positive values indicate rising unfinished work.
        late = [(t, b) for t, b in backlog_samples if t >= self.duration_seconds - 300]
        if len(late) >= 2:
            mean_t = sum(t for t, _ in late) / len(late)
            mean_b = sum(b for _, b in late) / len(late)
            denominator = sum((t - mean_t) ** 2 for t, _ in late)
            slope_per_second = (
                sum((t - mean_t) * (b - mean_b) for t, b in late) / denominator
                if denominator
                else 0.0
            )
            queue_growth = max(0.0, slope_per_second * 60.0)
        else:
            queue_growth = outstanding / elapsed_minutes

        metrics = ScenarioMetrics(
            throughput_tasks_per_min=round(completions / elapsed_minutes, 6),
            average_wait_seconds=round(average_wait, 6),
            queue_growth_per_min=round(queue_growth, 6),
            junction_occupancy=round(min(1.0, junction_busy_seconds / self.duration_seconds), 6),
            deadlock_events=0,
            task_arrivals=arrivals,
            task_completions=completions,
            route_service_started_count=route_service_started_count,
            tasks_not_started_by_horizon=tasks_not_started_by_horizon,
            route_service_wait_total_seconds=round(route_service_wait_total, 6),
            censored_wait_observation_seconds=round(censored_wait_observation, 6),
            bypass_task_count=bypass_task_count,
            high_risk_context_arrival_count=high_risk_context_arrival_count,
            conditional_policy_trigger_count=conditional_policy_trigger_count,
        )
        return SimulationRun(
            run_id=f"{manifest.experiment_id}-seed-{manifest.seed}",
            experiment=manifest,
            backend="discrete_event",
            metrics=metrics,
            started_at=datetime.now(UTC),
            notes=[
                "CPU-only discrete-event queueing model; not NVIDIA Isaac Sim or a physics-based digital twin.",
                "Priority tasks receive queue precedence and longer service windows by explicit scenario assumption.",
                f"Routing policy: {p.routing_policy}; bypass ratio: {p.bypass_ratio:.2f}; actual bypass tasks: {bypass_task_count}; conditional triggers: {conditional_policy_trigger_count}.",
                "Task-level random variates are pre-sampled to improve paired-policy comparability (common random numbers).",
                "No geometry, collision, sensor, or deadlock model; deadlock_events=0 is not a safety result.",
                "average_wait_seconds is arrival-to-route-service-start wait among tasks whose route service began before the horizon; unfinished waits are excluded.",
                "tasks_not_started_by_horizon counts right-censored tasks; censored_wait_observation_seconds is a separate horizon-limited descriptive metric, not a completed-wait mean.",
                f"Simulated duration: {self.duration_seconds:.0f}s; robots: {self.robot_count}; arrivals: {arrivals}; route_service_started: {route_service_started_count}; not_started_by_horizon: {tasks_not_started_by_horizon}; completed: {completions}.",
            ],
        )
