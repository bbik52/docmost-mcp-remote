# 0006. Apache License 2.0

## Status
Accepted. Replaces the license part of ADR 0001 (MIT).

## Context
The project started under MIT. It is meant to grow into a tool that other
people run and contribute to. Changing the license later needs the consent of
every contributor, which becomes unrealistic once there are many; the choice
is cheap only before the first outside contribution. Until now all code was
written by the maintainer, so the change is possible without asking anyone.

Options considered:
- **MIT**: short and permissive, but says nothing about patents or about the
  terms of contributions.
- **Apache 2.0**: permissive like MIT, with an explicit patent grant and
  patent-retaliation clause, and section 5 makes contributions fall under the
  same license without a separate agreement.
- **AGPL-3.0**: forces anyone who runs a modified version as a service to
  publish it, but many companies forbid AGPL software, which would cost users
  and contributors.
- **A CLA**: would keep the option of relicensing or a commercial edition, at
  the cost of deterring contributors. No commercial edition is planned.

## Decision
- The project is licensed under the Apache License 2.0 (`LICENSE`), with a
  `NOTICE` file.
- Contributions are accepted under the same license through its section 5.
  No CLA.
- Signing is deferred: no DCO (`Signed-off-by`) requirement on commits and no
  signed release artifacts for now. Both can be added later without changing
  the license.
- The rest of ADR 0001 stands: clean implementation, nothing copied from
  docmost-mcp-oss or Docmost. If code from docmost-mcp-oss (MIT) is ever
  copied, its MIT notice goes into `NOTICE`; MIT code can be included in an
  Apache 2.0 project.

## Consequences
- Users and companies get an explicit patent license; contributors' patent
  rights are licensed too.
- Anyone may still build a closed or hosted product on the code; this is
  accepted as the price of a permissive license.
- The license does not cover the project name. A short note on the name is
  in DESIGN.md ("Contributions and project security").
