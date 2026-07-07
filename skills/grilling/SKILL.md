---
name: grilling
description: Grill the user relentlessly about a plan or design. Use when the user wants to stress-test a plan before building, or uses any 'grill' trigger phrases.
---

Grilling is interactive — it needs a human answering one question at a time, so run it only in a human-driven session (never inside an autonomous loop such as `/autodrive`, `/domino`, or `/orchestrate`, where no human is at the keyboard).

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the codebase, look it up rather than asking me. The *decisions*, though, are mine — put each one to me and wait for my answer.

Do not enact the plan until I confirm we have reached a shared understanding.

<!-- Adapted from mattpocock/skills (MIT): skills/productivity/grilling. Only the
     opening interactive/human-driven guard is added — this repo is autonomous by
     default, so the loop must never fire an interview. The rest is verbatim. -->
