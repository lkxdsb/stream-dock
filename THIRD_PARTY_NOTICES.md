# Third-party notices

StreamDock uses independent open-source components for selected local processing capabilities.

## Local document parsing component

The optional PDF parsing environment integrates MinerU as a replaceable local provider.

- Project: https://github.com/opendatalab/MinerU
- Installed development version: 3.4.4
- License copy: `licenses/mineru-license.md`
- Integration boundary: `pdf_engine/providers/mineru.py`

StreamDock's task orchestration, parsing strategy, post-processing, quality checks, and product interface are maintained separately from the provider.
