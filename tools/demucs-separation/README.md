# Demucs Source Separation

Four-stem audio source separation (vocals / drums / bass / other). The default ships a frequency-band heuristic that runs anywhere; if `demucs` is installed locally the tool can swap in a higher-quality model.

Why not bundle the real Demucs by default: htdemucs pulls 600 MB+ of torch weights on first use and the Windows wheels are temperamental. See the AMBITION buffer-pool note.

## Install
```
cd tools/demucs-separation
uv sync
```

## Test
```
uv run pixie validate demucs-separation --summary
```
