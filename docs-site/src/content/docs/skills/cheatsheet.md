---
title: Cheatsheet
description: Copy-paste prompts for the most-used skills.
sidebar:
  order: 8
---

Open Claude Code in the Pixie repo, then type any of these.

## Add a tool

```text
Add a Pixie tool that <does the thing>
```
```text
Add github.com/<user>/<repo> as a Pixie tool
```
```text
Wrap ./scripts/<file>.py as a Pixie tool
```
```text
Convert ./<notebook>.ipynb to a Pixie tool
```
```text
Wrap ffmpeg as a Pixie tool
```
```text
Import ./shared/<tool>.zip
```

## Edit / maintain

```text
Update the foo tool: add a slider for X from 0 to 100
```
```text
Rename foo to bar
```
```text
Duplicate the foo tool as foo-v2
```
```text
Archive foo (I'll bring it back later)
```
```text
Remove the foo tool permanently
```
```text
Lint the foo tool
```
```text
Migrate the foo tool to the latest schema
```
```text
Re-validate every tool
```

## Secrets & data

```text
Set the ANTHROPIC_API_KEY for the rag-with-citations tool
```
```text
Fetch https://example.com/data.csv into the foo tool
```
```text
Fetch the kaggle.com/datasets/foo/bar into the baz tool
```
```text
Import ~/Downloads/iris.csv into the foo tool
```

## Runs & outputs

```text
Show me the last 5 runs of the foo tool
```
```text
Find PNG outputs from this week
```
```text
Label the last run of foo "final-budget"
```
```text
Star run abc123
```
```text
Export run abc123 to ./exports
```
```text
Export run abc123 as a markdown report
```
```text
Export this output as SVG
```
```text
Bulk-export all starred runs from the lorenz tool
```
```text
Copy this output to ~/Documents/results.csv
```
```text
Copy this text to the clipboard
```
```text
Open the artefacts folder for foo in Explorer
```
```text
Clear runs older than 30 days from foo
```

## Workspaces & tags

```text
Create a "Finance" workspace
```
```text
Add black-scholes-greeks to the Finance workspace
```
```text
Tag foo as 'nlp' and 'production'
```
```text
Cite arxiv.org/abs/2106.09685 on the foo tool
```

## Share

```text
Package the foo tool as a zip
```
```text
Set up "reports" as an export target pointing at ~/Documents/Reports
```

## Debug

```text
Why is the foo tool failing validation?
```
```text
Show me the stderr for foo
```
```text
Run pixie doctor
```
```text
Is Pixie running?
```
```text
List all tools
```
```text
Validate foo against its reference fixtures
```

---

If the routing picks a different skill from what you wanted, just say so —
e.g. "no, use `update-tool` not `debug-tool`" — and Claude Code will
correct course.
