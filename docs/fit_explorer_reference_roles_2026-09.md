# Fit Explorer reference roles — 2026-09

## Decision

A species in a CAESAR FitSet is not automatically an absolute physical anchor.
The old Explorer adapter treated `O4` specially by name. That rule is retired:
only an explicit `reference_roles.<species>.anchor_role = "ELIGIBLE"` may enter
an absolute-amount check, and eligibility is not a PASS. The next Explorer
phase must first establish window-specific observability.

This preserves existing evidence. It changes its scope, not its bytes:

- Historic cold/O4 evidence remains evidence that a weak O4 column can absorb a
  fixed residual pattern in that cold window. It is not a transferable claim
  that every O4-containing window has a valid O4 absolute anchor.
- ASIA-AQ 436.45–460.36 nm reports that failed solely on an O4 amount ratio are
  superseded for T2 interpretation by `ANCHOR_OBSERVABILITY_NOT_ESTABLISHED`.
  They remain immutable execution records and must not be deleted or overwritten.

## FitSet schema

`reference_roles` is optional for backward compatibility. If omitted, every
reference remains a modeled fit column but all absolute anchors are
`UNSPECIFIED`; T2 absolute amount is therefore `UNAVAILABLE`, never PASS/FAIL.

```json
{
  "reference_roles": {
    "NO2": {"fit_role":"MODELED_REFERENCE", "registration_role":"PREFERRED",
            "anchor_role":"UNSPECIFIED"},
    "H2O": {"fit_role":"MODELED_REFERENCE", "registration_role":"LINKED",
            "anchor_role":"UNSPECIFIED"},
    "CHOCHO": {"fit_role":"MODELED_REFERENCE", "registration_role":"LINKED",
               "anchor_role":"UNSPECIFIED"},
    "O4": {"fit_role":"OPTIONAL_REFERENCE", "registration_role":"LINKED",
           "anchor_role":"INELIGIBLE",
           "reason":"ANCHOR_OBSERVABILITY_NOT_ESTABLISHED"}
  }
}
```

Allowed values:

- `fit_role`: `MODELED_REFERENCE`, `OPTIONAL_REFERENCE`
- `registration_role`: `PREFERRED`, `LINKED`, `NONE`
- `anchor_role`: `ELIGIBLE`, `INELIGIBLE`, `UNSPECIFIED`

`PREFERRED` denotes a candidate wavelength-registration driver, not a target
and not an absolute concentration standard. In many blue-channel CAESAR
FitSets this will be NO2 because its resolved differential structure identifies
shift/squeeze. The later observability phase must demonstrate this per window;
the name `NO2` itself is not a rule.

## Consequence for T2

T2 still rejects high differential collinearity. Its absolute-amount branch
now evaluates only explicit eligible species. Without one it returns
`UNAVAILABLE`; anchor-independent coefficient, residual, seed and boundary
diagnostics remain available but cannot manufacture an absolute PASS.

This is a semantic correction based on the ACES/BBCEAS retrieval model: fit
reference inclusion, wavelength registration, interference control, and
independent validation are separate jobs.
