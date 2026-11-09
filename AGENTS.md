# Rules

- All tasks are ran on docker `cadence-ddi:25.10.000-patched` with all cpu cores and gpu enabled

- Use `innvous` for placement and routing; `Genus` for synthesis, `Xcelium` for simulation

- Targeting Reproducing Paper: `./Paper/Tri-Oracle - A 17.78μJ per Token Vision-Language Model Accelerator with Token-Attention-Weight Redundancy Prediction.pdf`

- Library Cells are available at `~/Documents/pdks`

- Be very careful to not saturate either CPU or GPU memories.
