# ProPS adaptations (fill during Phase 0)

Read Zhou et al., "Prompted Policy Search" (NeurIPS 2025, arXiv:2511.21928) §3
and complete this table. It becomes the "Adaptations" section of the report.

| Original ProPS element | Our IT/OT security adaptation | Reason |
|---|---|---|
| Policy = continuous action params | Bounded, mixed-type defensive policy (enums, subsets, floats, ints) | Security controls are categorical/bounded |
| Numeric reward from env | Log-derived reward R(π)=w_dD+w_cC+w_aA+w_rQ-w_fF-w_lL | Detection pipeline gives noisy, multi-objective signal |
| (fill in) | (fill in) | (fill in) |
