<!-- house-style: template — fill this file in, then delete this line -->

# Architecture

How repo is put together.

<!--
  Write this once the shape has settled, and update it when the shape
  changes. It is for someone who wants to change the project, rather than
  someone who wants to use it.

  What belongs here:
    - the modules and what each one is for
    - the main data flow
    - the decisions that are not obvious, with the reason for each
    - the boundaries: what may not import what

  What does not belong here:
    - the product pitch (README)
    - the traps and the release procedure (AGENTS.md)
    - a class-by-class tour of the code
-->

## The shape

<!--
  A short paragraph, then the module table.

  The package tree, with one line each:

  | Module | What it is responsible for |
  | --- | --- |
  | `src/entry` | ... |
-->

## The data flow

<!--
  Where the data comes from, what happens to it, where it goes. A diagram
  in text form is enough:

  ```
  input → parse → transform → output
  ```
-->

## Decisions worth knowing about

<!--
  The choices that a reader would otherwise assume were accidents. Each one
  gets the reason, and the cost it implies.

  ### The worker uses spawn, not fork

  The worker process has to survive a parent that exits, so it is started
  with `multiprocessing.get_context("spawn")`. The cost is that the fixture
  in the tests patches `get_context` rather than the module attributes.
-->

## Boundaries

<!--
  What may not import what. This is the section that keeps a codebase from
  turning into a ball of mud. Write it before it is needed.
-->
