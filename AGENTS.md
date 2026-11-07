# DoorDash Project (NOVA Hackathon) — Agent Guide

## Ticketing system (read this first)

Work is tracked in local tickets, not in chat. Each ticket is a Markdown file in
`tickets/` (`T-001.md`, `T-002.md`, ...) managed by `tickets.js` (Node, no dependencies).
Tickets are committed to git together with the code they describe.

### Commands
```bash
node tickets.js board                          # everything, grouped by status
node tickets.js next                           # highest-priority unclaimed todo
node tickets.js new "Title" --priority p1 --labels backend --body "What and why"
node tickets.js claim T-004 --as claude        # assign to yourself + in-progress
node tickets.js note T-004 "Added /orders endpoint, tests pending"
node tickets.js status T-004 blocked "Need the menu API schema"
node tickets.js done T-004 "Merged in abc123"
```
Statuses: `todo`, `in-progress`, `blocked`, `review`, `done`. Priorities: `p0` (urgent) to `p3`.

### Rules for agents
1. **Start of a session:** run `node tickets.js board`. If the user didn't name a task, pick up `node tickets.js next`.
2. **Before writing code**, claim the ticket (`claim <id> --as <your-name>`, e.g. `claude`, `codex`). Never take a ticket someone else has claimed unless the user says to (`--force`).
3. **Offload, don't expand:** when you find work that is out of scope for your current ticket (a bug, a follow-up, a TODO), create a new ticket for it with `new` instead of doing it now. Put enough context in `--body` that another agent or teammate can start cold.
4. **Log progress** with `note` at meaningful checkpoints: what changed, which files, what's left. The log is the hand-off for whoever picks it up next.
5. **Blocked?** Set `status <id> blocked "<reason>"` and stop or move on. Don't guess.
6. **Finished?** Tick the acceptance criteria in the ticket file, then `done <id> "<summary / commit>"`. Use `review` instead when a human should check it first.
7. You may edit a ticket's Description and Acceptance criteria sections directly; change status, assignee and log entries only through `tickets.js` so the log stays accurate.
