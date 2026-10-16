# Isaac Sim Readiness — Not an Installation or Run Procedure

This document defines what must be confirmed before a future authorized session. It deliberately does not contain a one-click install or a command to run the project in Isaac Sim.

## Release and host must be confirmed first

As of 16 October 2026, NVIDIA's Isaac Sim 6.2.0 requirements page lists x86-64 Ubuntu 22.04/24.04 or Windows 11, minimum 32 GB RAM, 50 GB SSD and a GeForce RTX 4080 class GPU with 16 GB VRAM; the page currently lists Linux driver 595.58.03 for the tested configuration. NVIDIA notes Ubuntu 22.04 support is deprecated and that assets/extensions may need outbound internet access. These values are release-specific and must be checked against the actual installed software and institution host; do not change a managed machine's drivers without authorization. Source: [Isaac Sim 6.2 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html).

The project does not yet know which Isaac build or access method the provider will grant. **Do not pin an assumed release in a dependency lock until the real host is identified.** Record `Help > About`/installed `VERSION` file, OS, GPU/VRAM, driver, RAM, free disk, launcher path, network/asset access and host permission.

## Python environment isolation

The existing RESILIANT environment is used for the local project and may use a newer Python than the simulator. Do not install Isaac packages into it. NVIDIA's current Python installation guide explicitly advises a dedicated Python environment because the Isaac package set pins and may upgrade/downgrade dependencies; current pip examples use Python 3.12 for Isaac Sim 6.2.0. Source: [Isaac Sim Python environment installation](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_python.html).

Choose one route after the provider host is known:

- **Binary distribution:** use the Isaac install's own launcher/runtime for its scripts. Keep project Python isolated; pass validated manifests and exchange output files.
- **Python package install:** use a dedicated `env_isaacsim` environment in the simulator-supported Python version, never the existing project `.venv`.
- **Institution container/cloud:** use only the approved image/runtime and persistent storage conventions.

Do not mix binary-launcher assumptions with pip-environment assumptions.

## ROS 2 is optional, not Phase III's starting point

Prefer a direct standalone adapter first. Add ROS 2 only if the controller needs an external process or message bus. Then select the ROS distribution/workspace release from NVIDIA's exact version compatibility table, not from the default branch of a repository. References: [Isaac Sim 6.2 compatibility](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/compatibility.html) and [ROS 2 installation](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/install_ros.html).

## Robot integration standard

The first true robot integration must use a supported articulated wheeled mobile robot asset, joint/drive controller and physics stepping. Do not substitute a moving cube, scripted world-transform changes or a separate shadow queue model for the canonical control path. Keep the canonical RESILIANT policy function shared between CPU and Isaac adapters.

Start with one robot and one junction. Validate commanded and measured motion, simulation reset, contact events, task start/completion and output provenance. Scale to two robots, then ten, then the proposal target of 20–35 only after each earlier gate passes. Do not call collision/deadlock metrics zero if they are not instrumented.

Relevant NVIDIA references:

- [Basic Robot tutorial](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/introduction/quickstart_isaacsim_robot.html)
- [Articulation Controller](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/robot_simulation/articulation_controller.html)
- [Mobile Robot Controllers](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/robot_simulation/mobile_robot_controllers.html)
- [Contact Sensor](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/sensors/physics_sensors/contact_sensor.html)
- [Multiple Robot Scenarios](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/introduction/quickstart_isaacsim_robot.html)

Confirm links and APIs against the installed release before implementation because the documentation moves between releases.

## Future output package

Every run must export:

- validated manifest and schema version;
- run start/end and status (`succeeded`, `failed`, `timeout`, `incomplete`);
- code SHA, scenario/config SHA, asset identifiers/hashes and backend version;
- random seed, runtime/driver/GPU metadata (non-secret);
- per-robot command/observed telemetry and task/junction events;
- aggregate metrics with units and definitions;
- raw logs and exceptions;
- failure/invalidity reason if not successful.

The actual result importer must validate files against the existing `ExperimentManifest`/`SimulationRun` contracts. It must not trust CSV rows merely because they carry a `git_sha` field; provenance must be checked against host-side logs.

## Mandatory stop rule

At the end of Phase III, stop. No Isaac package install, asset download, GPU launch, host-driver modification, cloud job, port exposure or simulation run is authorized by this readiness plan. Wait for the user's explicit go-ahead and verify the actual host before beginning the runtime stage.
