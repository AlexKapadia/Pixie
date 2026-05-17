# Causal ATE Estimator

Estimate the average treatment effect of a binary treatment on a continuous outcome with optional measured confounders. Uses OLS adjustment, inverse-probability weighting, and a doubly robust cross-check. Refutations include a placebo permutation and a random-subset stability test.

This tool was originally specified to use DoWhy. We substituted a transparent sklearn-based estimator so the tool installs cleanly on Windows without DoWhy's heavy dependency stack.

## Install
```
cd tools/dowhy-causal-ate
uv sync
```

## Test
```
uv run pixie validate dowhy-causal-ate --summary
```
