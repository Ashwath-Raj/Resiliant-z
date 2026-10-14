# RESILIANT-Z: Autonomous Fleet Discovery and Self-Correction

> **"Don't just build fleets that know what to do. Build fleets that can discover when what they know is no longer enough."**

## About the Project

RESILIANT-Z started with a question that kept bothering me while researching autonomous systems:

**What happens when an autonomous fleet encounters a situation that its designers never explicitly anticipated?**

I've always been interested in AI systems that do more than generate an answer. My previous work with AI agents, multimodal systems, optimization, and self-improving workflows made me curious about what happens when those ideas are placed in a physical environment, where many autonomous agents interact and small decisions can create unexpected system-level behavior.

That led me into multi-robot systems.

I'm relatively new to robotics, so I wanted this project to be an opportunity to explore something outside what I already knew. Rather than starting with a familiar problem and simply attaching an AI model to it, I wanted to take a step back, research how autonomous fleets actually work, understand what existing systems already solve, and look for a gap that was interesting enough to build around.

I spent a lot of time running AI experiments, reading research around fleet management, multi-robot task allocation, digital twins, simulation-based optimization, active learning, and LLM-based robotics, and trying to understand where the current approaches stop.

What I kept seeing was that autonomous fleets are already very good at **executing known policies**.

They can assign tasks, plan routes, avoid collisions, balance workloads, optimize throughput, and recover from predefined failures.

But there is a difference between a system being able to operate autonomously and a system being able to recognize that **its own understanding of the environment is incomplete**.

That observation led to the question that became the foundation of RESILIANT-Z:

> **Can a fleet discover something about itself that its designers did not explicitly know?**

We decided to explore that question through a small but deliberately open-ended simulated warehouse.

---

## Architecture & Methodology

We built a simulated multi-robot warehouse where the fleet is given an operational model, but some fleet-level relationships are intentionally left unknown.

The robots continuously produce operational telemetry such as congestion, junction occupancy, queue growth, utilization, throughput, waiting time, task distribution, and traffic concentration.

When the observed behavior significantly deviates from what the current model expects, RESILIANT-Z does not simply execute a predefined recovery routine.

Instead, it treats the unexplained behavior as something worth investigating.

- **NVIDIA Nemotron** acts as the reasoning layer. It generates competing hypotheses about what could be causing the behavior and proposes experiments capable of distinguishing between them.
- **NVIDIA Isaac Sim** becomes the experimental laboratory. Rather than asking the model to imagine what would happen, we use controlled counterfactual simulations to actually test its hypotheses.
- **Nebius** provides the infrastructure for running these simulation workloads and scaling the investigation process.

The resulting loop is:

```text
Unexpected behavior
        ↓
Generate competing hypotheses
        ↓
Design an experiment
        ↓
Run counterfactual simulation
        ↓
Collect evidence
        ↓
Validate the relationship
        ↓
Update fleet knowledge
        ↓
Adapt policy

```

The LLM is deliberately not allowed to directly control the robots.

- Nemotron proposes.
- The deterministic experiment layer constrains and validates the proposal.
- Isaac Sim challenges it.
- Evidence decides whether it survives.

### An Example

Imagine a 35-robot warehouse where congestion suddenly begins growing around one particular junction.

There could be several possible explanations:

- **H1** $\rightarrow$ Junction occupancy is simply too high.
- **H2** $\rightarrow$ Priority-task concentration is causing traffic buildup.
- **H3** $\rightarrow$ The interaction between occupancy and priority-task concentration creates nonlinear congestion.

Instead of asking Nemotron to choose one explanation and treating its answer as truth, RESILIANT-Z turns these explanations into experimentally testable hypotheses.

The system can then create controlled scenarios, vary the relevant conditions, and observe how the fleet responds.

A relationship might eventually emerge such as:

$$\mathcal{O} > 0.73 \land \mathcal{P} > 0.35 \implies \text{nonlinear queue growth}$$

The important part is not the particular threshold.

The important part is that the relationship was not initially provided to the system as known fleet knowledge.

The system has to encounter the behavior, propose explanations, experiment, collect evidence, and validate the result before treating it as candidate operational knowledge.

That is the small-scale simulation we are using to explore a much larger idea.

---

## What We Found Interesting

The more we researched this problem, the more we realized that the individual technologies involved are not new.

- Digital twins already exist.
- Multi-robot optimization already exists.
- Active learning already exists.
- Simulation-based optimization already exists.
- LLM-based robotics research already exists.

So we are not claiming to have invented any of those technologies.

The interesting gap we found was at the intersection of them.

Most fleet-management systems fundamentally ask:

> _"Given what we already know about the environment, what should the fleet do?"_

RESILIANT-Z asks:

> _"What if the fleet's current understanding of its own behavior is incomplete?"_

That changes the role of simulation.

Instead of simulation being only a place to test a controller that has already been designed, we use it as an experimental environment for investigating the fleet itself.

It also changes the role of the LLM.

Instead of making an LLM directly control robots, we use it to generate competing explanations and questions that can be experimentally tested.

And it changes the meaning of an anomaly.

Instead of:

$$\text{Anomaly} \longrightarrow \text{Recovery}$$

we explore:

$$\text{Anomaly} \longrightarrow \text{Investigation} \longrightarrow \text{Hypothesis} \longrightarrow \text{Experiment} \longrightarrow \text{Evidence} \longrightarrow \text{Discovery}$$

That is the particular perspective we wanted to explore with RESILIANT-Z.

---

## Challenges We Ran Into

The hardest part was realizing that generating a convincing explanation is actually the easy part.

An LLM can explain almost anything.

The difficult question is:

> _How do we know whether the explanation is actually supported by the system's behavior?_

That changed the architecture considerably.

We deliberately treat Nemotron as a hypothesis generator rather than an oracle.

The AI can be wrong.

The simulator is there to challenge it.

The evidence determines whether the proposed explanation survives.

Another major challenge was telemetry.

A multi-robot environment generates an enormous amount of low-level information. Sending every robot coordinate, velocity, orientation, and timestamp to an LLM would be inefficient and would obscure the higher-level relationships we are actually interested in.

We therefore had to think about how to transform low-level robot state into meaningful fleet-level representations such as:

- `junction_occupancy`
- `queue_growth_rate`
- `priority_ratio`
- `robot_utilization`
- `traffic_concentration`
- `throughput_delta`
- `average_wait_time`

We also had to confront a more uncomfortable problem: how do we know that a "discovery" is actually a discovery?

It would be extremely easy to hardcode a known relationship and then construct a demo where the AI appears to discover it.

That would completely defeat the purpose.

So the intended experiment begins with the relevant relationship absent from the fleet's knowledge. The system has to generate hypotheses, perform controlled experiments, and validate the result on additional scenarios.

Simulation itself also cannot automatically be treated as truth.

A single interesting graph does not constitute a discovery. Randomness, initialization, configuration, and simulator artifacts can all produce misleading results.

That is why repeated experiments and independent validation are part of the investigation process.

---

## What I Learned

For me, this project has been as much about exploration as implementation.

Coming from a Computer Science and AI background, I was already comfortable with agents, optimization, software systems, and AI experimentation. Multi-robot systems introduced a very different way of thinking about state, coordination, physical constraints, interaction, and emergent behavior.

That was exactly why I wanted to work on this.

I didn't want to build something simply because I already knew how to build it.

I wanted to use the hackathon as an excuse to enter a field where I had more questions than answers, research what had already been done, find a meaningful gap, and then see whether I could build even a small simulation that demonstrated the idea.

One of the biggest lessons was that autonomy isn't simply about making a system capable of acting without a human.

A system can execute its instructions completely autonomously while still being dependent on humans to tell it what to do when the assumptions behind those instructions fail.

That distinction is what pushed us toward RESILIANT-Z.

It also changed how I think about AI agents in physical systems.

The goal does not always have to be:

> _"Make the AI control everything."_

Sometimes the more interesting role for AI is to ask better questions about the system it is operating around.

That led to one of the principles behind RESILIANT-Z:

> **The AI proposes. The simulator challenges. Evidence decides.**

---

## What's Next

This prototype is intentionally small.

The goal was not to claim that we have solved autonomous fleet management. The goal was to explore whether the underlying idea could actually work.

The next step would be to move from a controlled simulation toward increasingly realistic fleet telemetry and heterogeneous robot environments.

A future system could investigate questions such as:

- Can a fleet discover interaction effects between different robot types?
- Can it identify operational thresholds that were not explicitly modeled?
- Can it distinguish genuine system-level behavior from random variation?
- Can it select experiments based on how much uncertainty they are expected to remove?
- Can discovered knowledge be evaluated in shadow mode before influencing a live fleet?

There is also a longer-term connection to my interest in quantum computing and optimization.

Fleet management contains difficult combinatorial problems involving task assignment, routing, scheduling, and resource allocation. I don't want to add quantum computing just because it sounds futuristic, but I would like to eventually investigate whether parts of the optimization layer can be formulated as hybrid quantum-classical problems and compared honestly against strong classical baselines.

For now, however, the experiment is much simpler:

> _Can we give a fleet an incomplete understanding of itself, expose it to unexpected behavior, and have it experimentally discover something that was not explicitly programmed into its knowledge beforehand?_

That is what RESILIANT-Z is trying to find out.

And that is ultimately why we built it.

> **"Don't just build fleets that know what to do. Build fleets that can discover when what they know is no longer enough."**
