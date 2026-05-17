# BERTopic Modelling

Sentence-embedding topic model over a CSV of documents. Falls back to TF-IDF + KMeans if BERTopic/sentence-transformers cannot be loaded (e.g. CPU-only restricted envs).

## Install
```
cd tools/bertopic-modelling
uv sync
```

## Test
```
uv run pixie validate bertopic-modelling --summary
```
