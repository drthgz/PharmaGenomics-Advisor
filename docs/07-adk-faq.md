# ADK FAQ

> Quick answers for demo-day ADK questions in this project.

## 1) Do I need to run the ADK localhost webpage for this project demo?

No. The project supports a CLI ADK runtime path, so the demo can be run directly from terminal commands.

Recommended demo command:

```bash
python3 scripts/demo.py --runtime adk --vcf data/samples/sample_variants_storytelling.vcf
```

## 2) Is ADK GUI setup required to define the workflow?

No. The workflow is defined in code and executed from the CLI runtime.

Relevant implementation:

- `src/pipeline/adk_workflow.py`
- `scripts/demo.py`

## 3) Do I need an API key to run ADK mode here?

Not for the current local-first implementation.

- ADK runtime is installed locally in Python.
- The current demo path does not require cloud model credentials.
- You only need API keys if you add cloud-hosted model/tool integrations later.

## 4) What command should I use for non-ADK mode?

Use the local runtime command:

```bash
python3 scripts/demo.py --runtime local
```

## 5) Which mode should I show in the capstone video?

Show both, briefly:

1. Local runtime (`--runtime local`) for baseline reproducibility.
2. ADK runtime (`--runtime adk`) to demonstrate explicit ADK integration.

## 6) What are the key outputs to show judges?

After a run, show:

- `output/.../report.json`
- `output/.../report.md`
- `output/.../report.html`

These outputs demonstrate end-to-end execution from VCF input to clinical report artifacts.
