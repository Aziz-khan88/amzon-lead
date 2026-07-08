# Book Trailer Lead Finder Agent DNA Docs

This folder is the operating manual for the Book Trailer Lead Finder system. It documents the product frame, the agent roles, the skill catalog, and the end-to-end logic used to turn book discovery inputs into production-ready outreach leads.

## Files

- [PRF.md](PRF.md): Product Requirements Framework for what the system must do, what it must not do, and how success is measured.
- [PRODUCT_DNA.md](PRODUCT_DNA.md): The durable product identity, values, constraints, and decision rules.
- [SKILLS.md](SKILLS.md): A catalog of core UI, CLI, service, and agent skills.
- [WORKFLOWS.md](WORKFLOWS.md): The multi-agent workflows from discovery through delivery.
- [LOGIC_A_TO_Z.md](LOGIC_A_TO_Z.md): A step-by-step logic map covering the pipeline from input to export.

## Source Of Truth

These docs summarize the current Django app in `leadfinder/`, the project README, and the agent handbook in `AGENTS.md`. They are intended for operators, developers, and future agents working on the project.

When behavior conflicts with code, the code wins. Update these docs after changing pipeline behavior, scoring rules, export requirements, or compliance boundaries.
