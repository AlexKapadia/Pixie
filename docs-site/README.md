# Pixie docs

This repository hosts the documentation site for **Pixie** — a local-first
dashboard for running your personal Python tools and models from one place.

The live site: **https://alexkapadia.github.io/Pixie/**

## Local development

```bash
cd docs-site
npm install
npm run dev      # http://localhost:4321
npm run build    # static output in dist/
```

Built with [Astro Starlight](https://starlight.astro.build/).

## Deployment

`.github/workflows/docs.yml` rebuilds the site and publishes it to GitHub
Pages on every push to `main` that touches `docs-site/` or the workflow
file.

## Licence

[MIT](./LICENCE).
