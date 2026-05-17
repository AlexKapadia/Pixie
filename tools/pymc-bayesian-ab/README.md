# Bayesian A/B Test

Closed-form Beta-Binomial conjugate analysis of a two-arm conversion experiment with a configurable prior strength. Returns posterior densities, P(variant > control), expected relative lift, ROPE-aware decision recommendation.

This tool was originally specified to use PyMC. We substituted an exact closed-form Beta-Binomial implementation (analytically equivalent to the PyMC version for this likelihood) — same model, no JAX/Aesara dependency, much faster.

## Install
```
cd tools/pymc-bayesian-ab
uv sync
```

## Test
```
uv run pixie validate pymc-bayesian-ab --summary
```
