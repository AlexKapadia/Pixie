import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// https://astro.build/config
export default defineConfig({
  site: "https://alexkapadia.github.io",
  base: "/Pixie",
  trailingSlash: "ignore",
  integrations: [
    starlight({
      title: "Pixie",
      description:
        "A local-first dashboard for your personal tools and models. Add tools by talking to Claude Code.",
      logo: {
        src: "./src/assets/pixie-logo.png",
        alt: "Pixie logo",
        replacesTitle: false,
      },
      favicon: "/favicon.png",
      social: {
        github: "https://github.com/AlexKapadia/Pixie",
      },
      editLink: {
        baseUrl:
          "https://github.com/AlexKapadia/Pixie/edit/main/docs-site/",
      },
      customCss: ["./src/styles/custom.css"],
      head: [
        {
          tag: "meta",
          attrs: { name: "theme-color", content: "#7c3aed" },
        },
      ],
      lastUpdated: true,
      pagination: true,
      tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 4 },
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "Welcome to Pixie", slug: "start/welcome" },
            { label: "Install & first run", slug: "start/install" },
            { label: "Use the example tool", slug: "start/example-tool" },
            { label: "Add your first tool", slug: "start/first-tool" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "How Pixie works", slug: "concepts/overview" },
            { label: "Runtime & subprocesses", slug: "concepts/runtime" },
            { label: "The validator", slug: "concepts/validator" },
            { label: "Schema-driven UI", slug: "concepts/renderer" },
            { label: "Storage & runs", slug: "concepts/storage" },
            { label: "Secrets", slug: "concepts/secrets" },
          ],
        },
        {
          label: "Build a tool",
          items: [
            { label: "Tool anatomy", slug: "build/anatomy" },
            { label: "tool.json reference", slug: "build/tool-json" },
            { label: "HTTP contract", slug: "build/http-contract" },
            { label: "Input types", slug: "build/inputs" },
            { label: "Output types", slug: "build/outputs" },
            { label: "Layouts", slug: "build/layouts" },
            { label: "Fixtures & reference validation", slug: "build/fixtures" },
            { label: "Streaming outputs", slug: "build/streaming" },
            { label: "Tool patterns", slug: "build/patterns" },
          ],
        },
        {
          label: "Claude Code skills",
          items: [
            { label: "Overview", slug: "skills/overview" },
            { label: "Add tools", slug: "skills/add-tools" },
            { label: "Edit & maintain tools", slug: "skills/edit-tools" },
            { label: "Data & secrets", slug: "skills/data-secrets" },
            { label: "Runs, outputs & exports", slug: "skills/outputs" },
            { label: "Workspaces & organisation", slug: "skills/workspaces" },
            { label: "Diagnostics", slug: "skills/diagnostics" },
            { label: "Cheatsheet", slug: "skills/cheatsheet" },
          ],
        },
        {
          label: "Tools cookbook",
          autogenerate: { directory: "cookbook" },
        },
        {
          label: "Reference",
          items: [
            { label: "CLI", slug: "reference/cli" },
            { label: "HTTP API", slug: "reference/http-api" },
            { label: "Database schema", slug: "reference/database" },
            { label: "Configuration", slug: "reference/configuration" },
            { label: "Validator checks", slug: "reference/validator-checks" },
          ],
        },
        {
          label: "Contributing",
          items: [
            { label: "How to contribute", slug: "contributing/overview" },
            { label: "Dev environment", slug: "contributing/dev-setup" },
            { label: "Code style", slug: "contributing/style" },
            { label: "Adding a new input/output type", slug: "contributing/new-type" },
            { label: "Tests", slug: "contributing/tests" },
            { label: "Out of scope", slug: "contributing/out-of-scope" },
          ],
        },
        {
          label: "Help",
          items: [
            { label: "FAQ", slug: "help/faq" },
            { label: "Troubleshooting", slug: "help/troubleshooting" },
            { label: "Glossary", slug: "help/glossary" },
          ],
        },
      ],
    }),
  ],
});
