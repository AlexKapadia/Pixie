# Anomaly Detection (Isolation Forest)

Fit `sklearn.ensemble.IsolationForest` to a univariate time series with engineered features (rolling z-score, first-difference) and highlight detected anomalies. Reports the top-N anomalous timestamps, anomaly rate, and a histogram of anomaly scores.

## Install
```
cd tools/anomaly-detection-isolation-forest
uv sync
```

## Test
```
uv run pixie validate anomaly-detection-isolation-forest --summary
```
