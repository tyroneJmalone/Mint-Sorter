---
name: Python installation limitation
description: Environment-specific failure encountered when adding PDF editing dependencies.
---

Do not assume the managed Python package installer can add a package successfully in this workspace.

**Why:** Adding PyMuPDF through the package tool attempted to install into the immutable Nix interpreter and failed with permission denied, despite existing packages being available from the workspace package directory. The system-package tool also could not resolve python311Packages.pymupdf.

**How to apply:** Inspect the actual installer failure before retrying; do not repeat the same installation or bypass permissions. For PDF redaction, the existing MuPDF command-line runtime provided the required capability without a new dependency. If a different Python library is essential, resolve the install target explicitly.
