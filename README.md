# AI Tuition Assistant

An AI agent that answers tuition questions by combining a university policy document (served by an MCP server) with live tuition data (served by a REST API behind a Kong API gateway).

> Work in progress. Setup, gateway routes, MCP schema, test instructions, deployment URLs, costs and the demo video link will be added here as each phase is completed.

## Documents
- [Requirements (SRS)](docs/01_SRS.md)
- [Technical design](docs/02_Technical_Design.md)
- [Test plan](docs/03_Test_Plan.md)
- [Tuition policy document indexed by the MCP server](docs/University_Tuition_Policies.md)

## Quick start (local)
```bash
cp .env.example .env   # then fill in the values
docker compose up -d
```
