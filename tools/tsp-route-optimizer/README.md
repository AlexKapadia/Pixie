# TSP Route Optimiser

Solve the travelling salesman problem on a set of map points using OR-Tools (with a nearest-neighbour fallback for very large inputs or solver failures).

## Install
```
cd tools/tsp-route-optimizer
uv sync
```

## Test
```
uv run pixie validate tsp-route-optimizer --summary
```
